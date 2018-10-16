from __future__ import division

import pprint, json, sys, time, os, cmd, random, subprocess, logging
from operator import itemgetter
from multiprocessing import Process

import pandas as pd
import numpy as np
from scipy import stats as sc_stats

import requests

from flask import Flask, jsonify

RYU_API = "http://localhost:8080"

class MainMachineLearning():
   def __init__(self, spine_sw, flows):
      self.spines = spine_sw		
      self.spines_num = len(self.spines)
      self.flows = flows
      self.flows_num = len(self.flows)
      self.loads_arr = [load[3] for load in self.flows]

   def getReward(self, actions):
      gateways_load = np.zeros(self.spines_num)
      for i in xrange(0, len(actions)):
         gateways_load[actions[i]] += self.loads_arr[i]
      mean = np.mean(gateways_load)
      sem = sc_stats.sem(gateways_load)
      reward = (mean-sem)/mean
      return (gateways_load, reward)

   def create_route_plan(self, actions):
      new_flow = []
      for i in range(len(self.flows)):
           load = self.flows[i]
           new_flow.append((load[0], load[1], actions[i]+1, load[3]))
      return new_flow

   def train(self, episodes, epsilon):
      best_idx = 0
      history = [] 
      time1 = time.time()
      for i in range(episodes):
         actions = []
         for j in xrange(0, self.flows_num):
            # ----- Epsilon Greedy Algorithm -----
            # Generate random number from 0 to 1 (float) will ML explore 
            # new actions or use best previous actions for each flow_id. 
            # Smaller exploration rate (epsilon), smaller probability ML 
            # to find new actions and more higher to use previous best actions.
            is_explore = np.random.rand(1) < epsilon
            if is_explore or i==0:
               actions.append(np.random.randint(self.spines_num))
            else:
               actions.append(history[best_idx][0][j])
         gw_load, reward = self.getReward(actions)
         if len(history) < 1:
            best_idx = i
         elif reward > history[best_idx][1]:
            best_idx = i
         history.append([actions, reward, gw_load])
      best_history = history[best_idx]
      best_actions_final = best_history[0]
      best_reward_final = best_history[1]
      best_gw_loads_final = best_history[2]
      route_plan = self.create_route_plan(best_actions_final)
      training_time = time.time()-time1
      predicted_sem = sc_stats.sem(best_gw_loads_final)/np.mean(best_gw_loads_final)
      return route_plan, training_time, best_reward_final, best_gw_loads_final, predicted_sem

class TopologyHelper():
   def __init__(self):
      self.SPINE_SW = []
      self.LEAF_SW = []
      self.LOADS = []

   def get_switches(self):
      req = requests.get(RYU_API+'/stats/switches')
      switches = req.json()
      spine = [x for x in switches if x//100==1] # All spine sw have id 100-199
      leaf = [x for x in switches if x//200==1] # All leaf sw have id 200-299 (include l2_switch)
      self.SPINE_SW = sorted(spine)
      self.LEAF_SW = sorted(leaf)

   def get_switch_stats(self, dpid):
      """ example output :
      [ip_src, ip_dst, gw, size]
      """
      req = requests.get(RYU_API+'/stats/flow/'+str(dpid))
      resp = req.json()
      data = []
      for flow in [flow for flow in resp[str(dpid)] if len(flow['match'])>0] :
         if flow['match']['dl_type']==2048:
            match = flow['match']
            gw = flow['actions'][0].split(':')[1]
            flowsize = flow['byte_count']
            if 'nw_src' in match:
               data.append((match['nw_src'], match['nw_dst'], gw, flowsize))
      return data

   def get_leafes_stats(self):
      """ example output :
      [
         [ip_src, ip_dst, gw, size]
      ]
      """      
      self.get_switches()
      flows1 = []		
      for leaf in self.LEAF_SW:
         flows1 += self.get_switch_stats(leaf)
      time.sleep(1)
      flows2 = []		
      for leaf in self.LEAF_SW:
         flows2 += self.get_switch_stats(leaf)
      flows1 = sorted(flows1)
      flows2 = sorted(flows2)
      flows = [(flows1[i][0], flows1[i][1], flows1[i][2], flows2[i][3]-flows1[i][3]) for i in range(len(flows1))]
      self.LOADS = flows
      return flows

   def get_gateways_flows(self):
      """ example output :
      {
         "101" : {
            "flows" : [{
               "ip_src" : ...,
               "ip_dst" : ...,
               "size" : ...
            }],
            "total" : ...
         }, ...
      }
      """
      gateways = {}
      flows = self.get_leafes_stats()
      for gw in self.SPINE_SW:
         gateways[str(gw)] = {'flows':[], 'total':0}
      for flow in flows:
         gwid = str(100 + int(flow[2]))
         flows = {
            "ip_src": flow[0],
            "ip_dst": flow[1],
            "size": flow[3]
         }
         gateways[gwid]["flows"].append(flows)
         gateways[gwid]["total"] += flow[3]
      return gateways

   def calc_sem_total(self, loads):
      loads = np.array(loads)
      mean = np.mean(loads)
      total = np.sum(loads)
      sem = sc_stats.sem(loads)/mean
      return sem, total

   def get_stats(self):
      gateways = self.get_gateways_flows()
      loads = []
      for gw in gateways:
         loads.append(gateways[gw]["total"])
      sem, total = self.calc_sem_total(loads)
      data = {}
      data["sem"] = sem
      data["total"] = total
      return data

   def send_flow_config(self, dpid, flow, pkt_type):
      host_ori, host_dst, outport, _ = flow
      data = {
         "dpid": dpid,
         "table_id": 0,
         "actions": [{
            "type": "OUTPUT",
            "port": outport
         }]
      }
      if pkt_type=='arp':
         data["match"] = { "arp_tpa": host_dst, "dl_type": 2054 }
      else:
         data["match"] = { "nw_dst": host_dst, "dl_type": 2048 }
      if host_ori!='0.0.0.0':
         if pkt_type=='arp':
            data["match"]["arp_spa"] = host_ori
         else:
            data["match"]["nw_src"] = host_ori
      _ = requests.post(RYU_API+'/stats/flowentry/modify', json=data )
   
   def exec_route_plan(self, flows=[]):
      for flow in flows:
         leaf = 200 + int(flow[0].split('.')[2])
         self.send_flow_config(leaf, tuple(flow), 'arp')
         self.send_flow_config(leaf, tuple(flow), 'ip4')

""" --- Flask API Server --- """
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
topoh = TopologyHelper()

@app.route('/stats', methods=['GET'])
def flask_stats():
   """ example output :
   {
      "101" : {
         "flows" : [{
            "ip_src" : ...,
            "ip_dst" : ...,
            "size" : ...
         }],
         "total" : ...
      },
      "sem" : ...
      "total: ...
   }
   """
   return jsonify(topoh.get_stats())

@app.route('/optimize', methods=['GET'])
def flask_optimize():
   episode_num = 1000
   exploration_rate = 0.15
   ml = MainMachineLearning(topoh.SPINE_SW, topoh.LOADS)
   route_plan, train_time, best_reward, pred_gw_loads, predicted_sem = ml.train(episode_num, exploration_rate)
   time1 = time.time()
   topoh.exec_route_plan(route_plan)
   time2 = time.time()-time1
   loads = list(pred_gw_loads)
   resp_body = {
      'train_time': train_time,
      'totals': sum(loads),
      'sem': predicted_sem,
      'reconfig_time': time2
   }
   return jsonify(resp_body)

def run_lb_api():
   app.run(host='0.0.0.0', debug=False)

def run_ryu_rest():
   time.sleep(1)
   proc = subprocess.Popen("PYTHONPATH=. /usr/local/bin/ryu-manager ryu.app.ofctl_rest ryu_lb.py --observe-links", shell=True)
   proc.wait()

def run_parallel(*fns):
   proc = []
   for fn in fns:
      p = Process(target=fn)
      p.start()
      proc.append(p)
   for p in proc:
      p.join()

if __name__ == '__main__':
   run_parallel(run_ryu_rest, run_lb_api)