from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle, TA_CENTER
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, SimpleDocTemplate, Spacer, Image, KeepTogether, LongTable, TableStyle, PageBreak
from pymongo import MongoClient
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.lib.colors import PCMYKColor, HexColor, blue, red
from reportlab.graphics.shapes import Drawing, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.textlabels import Label
import os
import pandas as pd
import sys
import math


def printf(data):
    print(data, flush=True)

def getSerialNumberFromOsip(ip,opt):
    df_all = pd.read_csv(os.environ['UPLOADPATH'] + os.environ['RACKNAME']+'.csv')
    if opt == 0:
        return(df_all[df_all['OS_IP'] == ip]['System S/N'].values[0])
    elif opt == 1:
        return(df_all[df_all['IPMI_IP'] == ip]['System S/N'].values[0])

def cleanUnits(unitsList, opt):
    if not all(x == unitsList[0] for x in unitsList): 
        return('Invalid Units!')
    if opt == 'all':
        if all(x == unitsList[0][0] for x in unitsList[0]):
            return unitsList[0][0]
        else:
            return ', '.join(unitsList[0])
    else:
        return unitsList[0][opt]

mongoport = int(os.environ['MONGOPORT']) # using in jupyter: 8888
rackname = os.environ['RACKNAME'].upper() 
client = MongoClient('localhost', mongoport) # using in jupyter: change localhost to 172.27.28.15
db = client.redfish
collection = db.servers
collection2 = client.redfish.udp
bmc_ip = []
timestamp = []
serialNumber = []
modelNumber = []
bmcVersion = []
biosVersion = []
bmc_event = []
bmcMacAddress = []
benchmark_node = []
benchmark_data = []
benchmark_unit = []
benchmark_name = {}

for data in list(collection2.find({})):
    if data['star'] != 1:
        continue
    elif data['benchmark'] not in benchmark_name:
        benchmark_name[data['benchmark']] = 1
    else:
        benchmark_name[data['benchmark']] += 1
n = 6
benchmark_map = {}
for key, value in benchmark_name.items():
    for i in range(math.ceil(value/n)):
        if i < math.ceil(value/n) -1:
            benchmark_map[key+ '|' + str(i+1)] = list(range(i*n,i*n+n))
        else:
            benchmark_map[key+ '|' + str(i+1)] = list(range(i*n,value))

for i in range(len(benchmark_map)):
    benchmark_node.append([])
    benchmark_data.append(('N/A'))
    benchmark_unit.append([])


for i, bm in enumerate(list(benchmark_map.keys())):
    counter = 0
    skip = benchmark_map[bm][0]
    cur_benchmark_data = []
    for data in list(collection2.find({})):
        if data['star'] == 1 and data['benchmark'] in bm and skip != 0:
            skip -= 1
            continue
        elif data['star'] == 1 and data['benchmark'] in bm and counter < len(benchmark_map[bm]):
            try:
                benchmark_node[i].append(getSerialNumberFromOsip(data['os_ip'],0))
            except:
                benchmark_node[i].append('N/A')
            try:
                cur_benchmark_data.append(data['raw_result'])
            except:
                cur_benchmark_data.append('N/A')
            try: 
                benchmark_unit[i].append(data['unit'])
            except:
                benchmark_unit[i].append('N/A')
            counter += 1
    cur_benchmark_data = list(map(list, zip(*cur_benchmark_data)))
    cur_benchmark_tuple = []
    for oneList in cur_benchmark_data:
        cur_benchmark_tuple.append(tuple(oneList))
    benchmark_data[i] = cur_benchmark_tuple
 
for i in collection.find({}):
    try:
        bmc_ip.append(i['BMC_IP'])
    except:
        bmc_ip.append('N/A')
    try:
        timestamp.append(i['Datetime'])
    except:
        timestamp.append('N/A')
    try:
        bmcMacAddress.append(i['UUID'][24:])
    except:
        bmcMacAddress.append('N/A')
    try:
        serialNumber.append(getSerialNumberFromOsip(i['BMC_IP'],1))
    except:
        serialNumber.append('N/A')
    try:
        modelNumber.append(i['Systems']['1']['Model'])
    except:
        modelNumber.append('N/A')
    try:
        bmcVersion.append(i['UpdateService']['SmcFirmwareInventory']['1']['Version'])
    except:
        bmcVersion.append('N/A')
    try:
        biosVersion.append(i['UpdateService']['SmcFirmwareInventory']['2']['Version'])
    except:
        biosVersion.append('N/A')
        
serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount = ([] for i in range(8))

for j in collection.find({}):
    try:
        serialNum.append(getSerialNumberFromOsip(j['BMC_IP'],1))
    except:
        serialNum.append('N/A')
    try:
        processorModel.append(j['Systems']['1']['CPU']['1']['Model'])
    except:
        processorModel.append('N/A')
    try:
        processorCount.append(j['Systems']['1']['ProcessorSummary']['Count'])
    except:
        processorCount.append('N/A')
    try:
        totalMemory.append(j['Systems']['1']['MemorySummary']['TotalSystemMemoryGiB'])
    except:
        totalMemory.append('N/A')
    try:
        memoryPN.append(j['Systems']['1']['Memory']['1']['PartNumber'])
    except:
        memoryPN.append('N/A')
    try:
        memoryCount.append(len(j['Systems']['1']['Memory']))
    except:
        memoryCount.append('N/A')
    try:
        driveModel.append(j['Systems']['1']['SimpleStorage']['1']['Devices'][0]['Model'])
    except:
        driveModel.append('N/A')
    try:
        driveCount.append(len(j['Systems']['1']['SimpleStorage']['1']['Devices']))
    except:
        driveCount.append('N/A')


res = [list(i) for i in zip(serialNumber, bmcMacAddress, modelNumber, bmc_ip, biosVersion, bmcVersion, timestamp)]
res2 = [list(j) for j in zip(serialNum, processorModel, processorCount, totalMemory, memoryPN, memoryCount, driveModel, driveCount)]

class Test(object):
    """"""

    #----------------------------------------------------------------------
    def __init__(self):
        """Constructor"""
        self.width, self.height = letter
        self.styles = getSampleStyleSheet()

    #----------------------------------------------------------------------
    def coord(self, x, y, unit=1):
        """
        http://stackoverflow.com/questions/4726011/wrap-text-in-a-table-reportlab
        Helper class to help position flowables in Canvas objects
        """
        x, y = x * unit, self.height -  y * unit
        return x, y

    #----------------------------------------------------------------------
    def run(self):
        """
        Run the report
        """

        self.doc = SimpleDocTemplate("cluster_report.pdf")
        #logo = "logo.jpg"
        #im = Image(logo, 1.5*inch, 1*inch)
        self.story = [Spacer(1, 0.5*inch)]
        #self.story.append(im)
        self.createLineItems()
        self.doc.build(self.story, onFirstPage=self.myFirstPage, onLaterPages=self.createDocument)
        printf("Notice: PDF generation finished!")
    #----------------------------------------------------------------------
    def createDocument(self, canvas, doc):
        """
        Create the document
        """
        self.c = canvas
        centered = ParagraphStyle(name="centered", alignment=TA_CENTER)
        
        smclogo = "supermicro.jpg"
        ssiclogo = "SSIC.png"
        self.c.drawImage(smclogo, self.width-85, self.height, 62, 30)
        self.c.drawImage(ssiclogo, self.width-200, self.height-765, 178, 30)
        #header_text = """<a name="TOP"/><strong>RACK REPORT: """ + rackname + """</strong>"""
        #p = Paragraph(header_text, centered)
        #p.wrapOn(self.c, self.width, self.height)
        #p.drawOn(self.c, *self.coord(0, 0, mm))

    #----------------------------------------------------------------------
    def myFirstPage(self, canvas, doc):
        normal = self.styles["Normal"]
        Title = "Test Report for " + rackname
        introduction = "Supermicro’s HPC and AI team (part of Supermicro Solution and Integration Center) is an elite team of software and hardware engineers. We generate and publish state-of-the-art benchmarks showcasing the performance of Supermicro’s wide array of Super Servers. We also work with the industry leading HPC and AI partners to generate the latest and greatest performance data."
        bmlogo = "logos.png"
        slogo = "ourSolutions.png"
        smclogo = "supermicro.jpg"
        ssiclogo = "SSIC.png"
        p = Paragraph(introduction, normal)
        w, h = p.wrap(self.doc.width, self.doc.topMargin)
        self.c = canvas
        self.c.drawImage(smclogo, self.width-85, self.height, 62, 30)
        self.c.drawImage(ssiclogo, self.width-200, self.height-765, 178, 30)
        self.c.setFont('Times-Bold',16)
        self.c.drawCentredString(self.width/2.0, self.height-10, Title)
        self.c.setFont('Times-Roman',12)
        self.c.drawString(10,30, "Test Report Generated by HPC & AI Team")
        p.drawOn(self.c, self.doc.leftMargin, self.height-65)
        self.c.drawCentredString(self.width/2, self.height-90, "Here are some examples of the benchmarks we have conducted:")
        self.c.drawImage(bmlogo, 75, self.height-300, 466, 200)
        self.c.drawCentredString(self.width/2, self.height-315, "Here is a list of other solutions that we offer:")
        self.c.drawImage(slogo, 40, self.height-520, 534, 200)
        self.c.drawCentredString(self.width/2, self.height-545, "For more information about our services please visit:")
        self.c.drawCentredString(self.width/2, self.height-580, "If you would like to see an in-depth view of our benchmarks please visit our blog:")
        self.c.setFillColor(red)
        self.c.drawCentredString(self.width/2, self.height-630, "NOTE: Both pages require company network to access")
        self.c.setFillColor(blue)
        self.c.setFont('Times-Bold',14)
        self.c.drawCentredString(self.width/2, self.height-560, "Supermicro Solution and Integration Center")
        self.c.drawCentredString(self.width/2, self.height-595, "HPC & AI Benchmarks")
        self.c.linkURL('http://solution.supermicro.com/', (165,225,445,245),relative=0)
        self.c.linkURL('http://172.31.32.198:8080/', (225,190,385,210),relative=0)
        
        
        #self.c.drawCentredString(self.width/2.0, self.height-20, introduction)
        #self.c.setFont('Times-Roman',9)
        #self.c.drawString(inch, 0.75 * inch, "First Page / %s" % pageinfo)
        #self.c.showPage()
        
    #----------------------------------------------------------------------
    def createLineItems(self):
        """
        Create the line items
        """
        spacer = Spacer(width=0, height=35)
        #Summary and Hardware Tables
        text_data = ["Serial Number", "BMC MAC Address", "Model Number", "BMC IP", "BIOS Version", "BMC Version", "Timestamp"]
        text_data2 = ["Serial Number", "CPU Model", "CPU Count", "Memory (GB)", "DIMM PN", "DIMM Count", "Drive Model", "Drive Count"]

        d = []
        d2 = []
        font_size = 10
        centered = ParagraphStyle(name="centered", alignment=TA_CENTER)
        for text in text_data:
            ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
            p = Paragraph(ptext, centered)
            d.append(p)
        for text in text_data2:
            ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
            p = Paragraph(ptext, centered)
            d2.append(p)

        data = [d]
        data2 = [d2]

        line_num = 1
        line_num2 = 1
        formatted_line_data = []
        count = collection.count_documents({})
        for x in range(count):
            line_data = res[x]
            for item in line_data:
                ptext = "<font size=%s>%s</font>" % (font_size-1, item)
                p = Paragraph(ptext, centered)
                formatted_line_data.append(p)
            data.append(formatted_line_data)
            formatted_line_data = []
            line_num += 1

        for y in range(count):
            line_data2 = res2[y]
            for item in line_data2:
                ptext = "<font size=%s>%s</font>" % (font_size-1, item)
                p = Paragraph(ptext, centered)
                formatted_line_data.append(p)
            data2.append(formatted_line_data)
            formatted_line_data = []
            line_num2 += 1

        table = Table(data, colWidths=[95, 90, 60, 75, 50, 50, 50, 65])
        table.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), (0xD0D0FF, 0xFFD0D0)),
            ("LINEBELOW", (0,0), (-1,-1), 1, colors.blue)
        ]))
        ptext = """
<link href="#TABLE1"
color="blue"
fontName="Helvetica">Jump to Summary Table</link> / <link href="#TABLE2"
color="blue"
fontName="Helvetica">Jump to Hardware Table</link> / <link href="#BM_TITLE"
color="blue"
fontName="Helvetica">Jump to Benchmark Report</link>"""
        ptext2 = """<a name="TABLE2"/><font color="black" size="12">Hardware Counts and Models</font>"""
        ptext1 = """<a name="TABLE1"/><font color="black" size="12">Cluster Summary for """ + rackname + """</font>"""
        p = Paragraph(ptext, centered)
        table2 = Table(data2, colWidths=[95, 60, 50, 60, 70, 50, 70, 50])
        table2.setStyle(TableStyle([
            ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
            ('BOX', (0,0), (-1,-1), 0.25, colors.black), 
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), (0xFFD0D0, 0xD0D0FF)),
            ("LINEBELOW", (0,0), (-1,-1), 1, colors.blue)
        ]))
        
        #dline = Drawing(450, 5)
        #line = Line(0, 0, 450, 0)
        #dline.add(Line(0, 0, 450, 0))
        paragraph1 = Paragraph(ptext1, centered)
        paragraph2 = Paragraph(ptext2, centered)
        paragraph1.keepWithNext = True
        paragraph2.keepWithNext = True
        #start by appending a pagebreak to separate first page from rest of document
        self.story.append(PageBreak())
        self.story.append(paragraph1)
        self.story.append(p)
        self.story.append(table)
        self.story.append(paragraph2)
        self.story.append(p)
        self.story.append(table2)
        
        #self.story.append(KeepTogether([Paragraph(ptext1, centered),dline,spacer,table,p,dline]))
        #self.story.append(PageBreak())
        #self.story.append(KeepTogether([Paragraph(ptext2, centered), dline, spacer, table2, p, dline]))
        
        ptext_bm = """<a name="BM_TITLE"/><font color="black" size="12">Benchmark Report</font>"""
        benchmarks_title = Paragraph(ptext_bm, centered)
        benchmarks_title.keepWithNext = True
        #self.story.append(PageBreak())
        #self.story.append(KeepTogether([benchmarks_title,spacer,dline]))
        self.story.append(benchmarks_title)
        self.story.append(p)
        #benchmark charts and tables
        
        #columns = ["Serial Number", "Results", "Unit"]
        #for text in columns:
        #    ptext = "<font size=%s><b>%s</b></font>" % (font_size, text)
        #    p2 = Paragraph(ptext, centered)
        #    d3.append(p2)
        for data, unit, node, name in zip(benchmark_data,benchmark_unit,benchmark_node,list(benchmark_map.keys())):
            if unit != 'N/A':
                data3 = []
                draw = Drawing(600,200)
                bar = VerticalBarChart()
                bar.x = 0
                bar.y = 0
                bar.height = 150
                bar.width = 500
                #bar.valueAxis.valueMin = min(min(data)) * 0.9
                bar.valueAxis.valueMin = 0 
                bar.valueAxis.valueMax = max(max(data)) * 1.15
                #bar.valueAxis.valueMax = 250000
                #bar.valueAxis.valueStep = 50000
                bar.strokeColor = colors.black
                bar.bars[0].fillColor = colors.lightblue
                bar.bars[1].fillColor = colors.lightgreen
                bar.bars[2].fillColor = colors.gold
                bar.categoryAxis.labels.angle = 20
                bar.categoryAxis.labels.dx = -35
                bar.categoryAxis.labels.dy = -10
                bar.data = data
                bar.categoryAxis.categoryNames = node
                #bar.categoryAxis.style = 'stacked'
                lab = Label() 
                lab2 = Label()
                lab.x = 0
                lab.y = 160
                lab2.x = 225
                lab2.y = 175
                lab.setText(cleanUnits(unit,'all'))
                lab.fontSize = 12
                lab2.setText(name)
                lab2.fontSize = 16
                draw.add(bar, '')
                draw.add(lab)
                draw.add(lab2)
                for item in node, data:
                    if item is node:
                        for a in item:
                            ptext = "<font size=%s>%s</font>" % (font_size-1, a)
                            p1 = Paragraph(ptext, centered)
                            formatted_line_data.append(p1)
                        data3.append(formatted_line_data)
                        formatted_line_data = []
                    if item is data:
                        for b_index, b in enumerate(item):
                            for c in b:
                                ptext = "<font size=%s>%s</font>" % (font_size-1, str(c) + ' ' + cleanUnits(unit,b_index))
                                p1 = Paragraph(ptext, centered)
                                formatted_line_data.append(p1)
                            data3.append(formatted_line_data)
                            formatted_line_data = []

                t = Table(data3, colWidths=90, rowHeights=40, style=[
                    ('GRID',(0,0), (-1,-1),0.5,colors.black),
                    ('ALIGN', (0,-1),(-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), (colors.gold, colors.lightgrey))
                ])
                self.story.append(KeepTogether([draw,spacer,t,spacer,p]))
                #self.story.append(PageBreak())
#----------------------------------------------------------------------
if __name__ == "__main__":
    t = Test()
    t.run()