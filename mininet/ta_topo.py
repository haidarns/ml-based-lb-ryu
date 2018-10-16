from __future__ import division

from mininet.net import Mininet
from mininet.node import OVSKernelSwitch
from mininet.topo import Topo
from mininet.node import Controller, RemoteController
from mininet.cli import CLI
from mininet.link import Intf, TCLink
from mininet.log import setLogLevel, info
from mininet.util import quietRun, run

import time, json, sys, subprocess, sys, pprint, datetime, csv
from random import randint
import requests
import pandas as pd

'''
Cisco Spine-and-Leaf Topology
src: https://www.cisco.com/c/dam/en/us/products/collateral/switches/nexus-7000-series-switches/white-paper-c11-737022.docx/_jcr_content/renditions/white-paper-c11-737022_3.jpg
'''
CONTROLLER_IP = '10.148.0.2'
CONTROLLER_ML_REST = 'http://'+CONTROLLER_IP+':5000/' # Default flask port (used as ML-LB API) is 5000 for development
CONTROLLER_RYU_REST = 'http://'+CONTROLLER_IP+':8080/' # Default ryu wsgi port is 8080

SCENARIO = {
"2": {        #h1  h2  h3  h4
   "loads" : [[10, 20, 30, 40], #100
              [15, 30, 45, 60], #150
              [20, 40, 60, 80]] #200
},
"4": {        #h1  h2  h3  h4  h5  h6  h7  h8
   "loads" : [[10, 20, 30, 40, 10, 20, 30, 40],  #200
              [15, 30, 45, 60, 15, 30, 45, 60],  #300
              [20, 40, 60, 80, 20, 40, 60, 80],  #400
              [25, 50, 75, 100, 25, 50, 75, 100]]  #500
},
"6": {       #h1  h2  h3  h4  h5  h6  h7  h8  h9  h10 h11 h12
   "loads" : [[10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40], #300
              [15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60], #450
              [20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80]] #600
},
"8": {       #h1  h2  h3  h4  h5  h6  h7  h8  h9  h10 h11 h12 h13 h14 h15 h16
   "loads" : [[10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40], #400
              [15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60], #600
              [20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80]] #800
},
"10": {      #h1  h2  h3  h4  h5  h6  h7  h8  h9  h10 h11 h12 h13 h14 h15 h16
   "loads" : [[10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40], #500
              [15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60], #750
              [20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80]] #1000
},
"12": {      #h1  h2  h3  h4  h5  h6  h7  h8  h9  h10 h11 h12 h13 h14 h15 h16
   "loads" : [[10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40, 10, 20, 30, 40], #500
              [15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60, 15, 30, 45, 60], #750
              [20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80, 20, 40, 60, 80]] #1000
}}

class LeafSpine( Topo ):
   def __init__( self, spine_num, leaf_num, host_per_leaf ):
      # Initialize topology
      Topo.__init__( self )
      of_ver = "OpenFlow13"
      hosts = []
      svr_hosts = []
      spine_sw = []
      leaf_sw = []
      # Creating L2 Switch
      l2_sw = self.addSwitch( name = "l2_sw", dpid = "%x" % (200), protocols = of_ver )
      # Creating SVR Hosts & linking to L2 Switch
      for x in xrange(1, 3):
         hname = "svr%s" % (x)
         svr = self.addHost( hname, ip = '10.0.0.%s' % (x) )
         self.addLink( l2_sw, svr, port1 = spine_num + x, delay = '1ms', use_htb = True)
      # Creating Spine Switch
      for x in xrange(1, spine_num+1):
         spine_sw.append(self.addSwitch( name = "sp_sw%s" % (x), dpid = "%x" % (100 + x), protocols = of_ver))
      # Creating Leaf Switch with Hosts
      for x in xrange(1, leaf_num+1):
         leaf = self.addSwitch( name="lf_sw%s"%(spine_num+x), dpid="%x"%(200+x), protocols=of_ver)
         leaf_sw.append(leaf)
         # Linking between Host & Leaf Switch
         for y in xrange(1, host_per_leaf+1):
            hname = "lf%s_h%s" % (x, y)
            host = self.addHost(hname, ip='10.0.%s.%s' % (x, y))
            self.addLink( leaf, host, port1=spine_num+y, bw=100, delay='1ms', use_htb=True)
      # Linking Spine Switch and L2 Switch/Leaf Switch
      for x in xrange(0, spine_num):
         self.addLink( spine_sw[x], l2_sw, port2=x+1, bw=100, delay='1ms', use_htb=True )
         for y in xrange(0, leaf_num):
            self.addLink( spine_sw[x], leaf_sw[y], port2=x+1, bw=100, delay='1ms', use_htb=True )

def send_req_lb(cmd):
   try:
      resp = requests.get(CONTROLLER_LB_REST+cmd)
      return resp.json()
   except Exception as e:
      print eval(e)
      return {}

def start_iperf_server(iperf_server, num_hosts):
   print '*** Starting Iperf Server *** '
   for i in range(num_hosts):
      iperf_server.cmd('iperf3 -s -p %s > ./log/iperf_server_%s.txt &' % (5001+i, 5001+i))
   print '(ok)'
   time.sleep(3)

def start_iperf_client(hosts, loads):
   print '*** Starting Iperf Client *** '
   i = 0
   for host in hosts:
      if 'lf' in host.name:
         host.cmd('iperf3 -u -b %sM -p %s -t 200 -c 10.0.0.1 &' % (loads[i], 5001+i))
         i += 1
   print '(ok)'
   time.sleep(3)

def start_voip_test(hosts):
   print '*** Starting VoIP Server *** '
   [host for host in hosts if host.name=='svr2'][0].cmd('./run-server.sh &')
   time.sleep(5)
   print '*** Starting VoIP Client *** '
   [host for host in hosts if host.name=='lf1_h1'][0].cmd('./run-client.sh &')
   time.sleep(5)

def parsing_voip_data(gw_num, load_var, lb_mode):
   script = "./get_voip_data.sh %s %s %s %s" % (gw_num, load_var, lb_mode, datetime.datetime.now().strftime('%H%M_%d%m%G'))
   proc = subprocess.Popen(script, shell=True)
   proc.wait()

def run_ta(gw_num, load_var, voip=False, sleep_time=10):
   """
   run_mode : - rr : testing round robin with ml optimization
              - iphash : testing round robin with ml optimization
   """
   run_data = {}
   spine_num = int(gw_num)
   leaf_num = spine_num
   num_lf_host = leaf_num*2
   topo = LeafSpine(spine_num, leaf_num, 2)
   net = Mininet(topo, controller=None, link=TCLink)
   net.addController(RemoteController(name='c0', ip=CONTROLLER_IP))
   net.start()
   net.pingAll()
   if voip:
      # CLI(net)
      start_voip_test(net.hosts)
   start_iperf_server(net.get('svr1'), num_lf_host)
   start_iperf_client(net.hosts, SCENARIO[gw_num]['loads'][int(load_var)-1])
   time.sleep(sleep_time)
   print '*** Get Network Stats *** '
   run_data['before'] = send_req_lb('stats')
   run_data['before']['lb_time'] = get_lb_time()
   print '*** Trigger LB Optimization *** '
   run_data['prediction'] = send_req_lb('optimize')
   print '(ok)'
   time.sleep(sleep_time)
   print '*** Get Network Stats *** '
   run_data['after'] = send_req_lb('stats')
   net.stop()
   print run_data
   return run_data

def settings_lb_mode(mode):
   resp = requests.post(CONTROLLER_RYU_REST+'lb/mode', json={'mode': mode})
   print resp.json()

def get_lb_time():
   resp = requests.get(CONTROLLER_RYU_REST+'lb/time')
   resp_dict = resp.json()
   print 'lb_time', resp_dict
   return resp_dict['time']

def run_scenario(config, lb_mode, iteration, voip):
   settings_lb_mode(lb_mode)
   if voip:
      print """********************************************
   Scenario %s Gw %s Load %s VoIP
********************************************""" % (lb_mode, config[0], config[1])
      run_ta(config[0], config[1], True, 60)
      parsing_voip_data(config[0], config[1], lb_mode)
   else:
      scenario_result = []
      for i in range(int(iteration)):
         print """********************************************
   Scenario %s Gw %s Load %s Iter %s
********************************************""" % (lb_mode, config[0], config[1], i+1)
         data = run_ta(*config)
         new_data = {}
         for key, val in data.iteritems():
            for key2, val2 in val.iteritems():
               new_data[key+'_'+key2] = val2 if type(val2)!=list else str(val2)
         scenario_result.append(new_data)
      df =  pd.DataFrame(scenario_result)
      filename = './result/scenario_%s_%s_%s_%s.csv' % (config[0], config[1], lb_mode, datetime.datetime.now().strftime('%H%M_%d%m%G'))
      df.to_csv(filename)

if __name__ == '__main__':
   try:
      gw_num = sys.argv[1]
      load_var = sys.argv[2]
      lb_mode = sys.argv[3]
      iteration = sys.argv[4]
      try:
         voip = sys.argv[5] == 'voip'
      except:
         voip = False
   except:
      print "ex.: %s <gw_number> <load_var> <run_mode> <iteration>" % (sys.argv[0])
   run_scenario((gw_num, load_var), lb_mode, iteration, voip)