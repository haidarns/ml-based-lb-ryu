from __future__ import division
from ryu.base import app_manager
from ryu.controller import ofp_event, handler
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet, ipv4, arp
from ryu.lib.packet import ether_types
from ryu.lib import dpid as dpid_lib
from ryu.app.wsgi import ControllerBase, WSGIApplication, route

from webob import Response
import copy, netaddr, json, time

LB_INSTANCE_NAME = 'lb_instance_app'
url = '/lb/'

class RESTHandler(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(RESTHandler, self).__init__(req, link, data, **config)
        self.lb_controller_app = data[LB_INSTANCE_NAME]
    
    @route('lb', url+'mode', methods=['POST'])
    def set_lb_mode(self, req, **kwargs):
        req_body = json.loads(req.body)
        self.lb_controller_app.lb_method = req_body['mode']
        resp_body = json.dumps({ 'mode': req_body['mode'] })
        return Response(content_type='application/json', body=resp_body)

    @route('lb', url+'time', methods=['GET'])
    def get_lb_time(self, req, **kwargs):
        resp_body = json.dumps({ 'time': self.lb_controller_app.lb_time })
        return Response(content_type='application/json', body=resp_body)

class Ryu_LB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = { 'wsgi': WSGIApplication }

    def __init__(self, *args, **kwargs):
        super(Ryu_LB, self).__init__(*args, **kwargs)
        wsgi = kwargs['wsgi']
        wsgi.register(RESTHandler, {LB_INSTANCE_NAME : self})
        self.sw_l2_list = {}
        self.sw_sp_list = {}
        self.sw_lf_list = {}
        self.spine_switch = []
        self.leaf_switch = []
        self.counter = {}
        self.spine_num = 0
        self.lb_method = 'rr'
        self.lb_time = 0

    def find_spine_leaf(self):
        self.spine_switch = list(self.sw_sp_list.keys())
        self.leaf_switch = list(self.sw_lf_list.keys())
        self.spine_num = len(self.spine_switch)
        self.counter = {}
        for leaf in self.leaf_switch:
            self.counter[leaf] = -1
        print "Spine:", self.spine_switch, "Leaf:", self.leaf_switch, 'Spine_Num:', self.spine_num, 'Counter', self.counter, 'Algo', self.lb_method

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    def forward_packet(self, datapath, msg, outport):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(outport)]
        out = parser.OFPPacketOut(datapath=datapath, actions=actions, in_port=msg.match['in_port'], data=msg.data, buffer_id=ofproto.OFP_NO_BUFFER)
        datapath.send_msg(out)

    def mod_host_flow(self, datapath, ip4_src, ip4_dst, outport):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if ip4_src!='0.0.0.0':
            self.logger.info("Flow: %s -> %s via gateway %s" % (ip4_src, ip4_dst, outport))
            match_ip = parser.OFPMatch(
                           eth_type = 0x800,
                           ipv4_src = ip4_src,
                           ipv4_dst = ip4_dst
                       )
            match_arp = parser.OFPMatch(
                           eth_type = 0x0806,
                           arp_spa = ip4_src,
                           arp_tpa = ip4_dst
                       )
        else:
            self.logger.info("Flow: all -> %s, via leaf_%s:%s" % (ip4_dst, datapath.id, outport))
            match_ip = parser.OFPMatch(
                           eth_type = 0x800,
                           ipv4_dst = ip4_dst
                       )
            match_arp = parser.OFPMatch(
                           eth_type = 0x0806,
                           arp_tpa = ip4_dst
                       )
        actions = [parser.OFPActionOutput(outport,0)]
        self.add_flow(datapath, 1, match_arp, actions)
        self.add_flow(datapath, 1, match_ip, actions)

    def _round_robin(self, dpid):
        self.counter[dpid] += 1
        if self.counter[dpid] == self.spine_num:
            self.counter[dpid] = 0
        return self.counter[dpid]

    def _ip_hashing(self, ip_src, ip_dst, sp_num):
        ip1 = int(hex(netaddr.IPAddress(ip_src)), 16)
        ip2 = int(hex(netaddr.IPAddress(ip_dst)), 16)
        xor_mod = (ip1 ^ ip2) % sp_num
        return xor_mod

    def _add_switch(self, dp):
        if(dp.id // 100) == 1:
            self.sw_sp_list[dp.id] = dp
            msg = 'Spine Switch'
        else:
            self.sw_lf_list[dp.id] = dp
            msg = 'Leaf Switch'
        print 'Switch join dpid=%s as %s' % (dp.id, msg)
        self.find_spine_leaf()
    
    def _del_switch(self, dp):
        if(dp.id // 100) == 1:
            del self.sw_sp_list[dp.id]
            msg = 'Spine Switch'
        else:
            del self.sw_lf_list[dp.id]
            msg = 'Leaf Switch'
        print 'Switch quit dpid=%s as %s' % (dp.id, msg)
        self.find_spine_leaf()

    @set_ev_cls(ofp_event.EventOFPStateChange, [handler.MAIN_DISPATCHER, handler.DEAD_DISPATCHER])
    def dispatcher_change(self, ev):
        if ev.datapath is None:
            return
        if ev.datapath.id is None:
            return
        dp = ev.datapath
        self.lb_time = 0
        if ev.state == handler.MAIN_DISPATCHER:
            self._add_switch(dp)
        elif ev.state == handler.DEAD_DISPATCHER:
            self._del_switch(dp)

    def _find_route(self, datapath, ip_src, ip_dst, msg):
        ip_src_split = ip_src.split('.') # Splitting IP into segments array [0, 1, 2, 3], 2nd is Leaf id, and 3rd is host id in leaf
        ip_dst_split = ip_dst.split('.')
        outport = 1
        dpid = datapath.id
        if dpid // 100 == 1:
            """
            If packet come from Spine Switch
            """
            outport = int(ip_dst_split[2]) + 1 # +1 because port 0 is for controller connection
            ip_src = '0.0.0.0'
        else:
            if dpid % 100 == int(ip_dst_split[2]):
                """
                If Packet come from leaf switch that link with destination host
                """
                outport = self.spine_num + int(ip_dst_split[3])
                ip_src = '0.0.0.0'
            else:
                """
                If Packet come from leaf switch that link with source host
                """
                if self.lb_method=='rr':
                    time1 = time.time()
                    outport = self._round_robin(dpid) + 1 # +1 because port 0 is for controller connection
                    self.lb_time += time.time()-time1
                else:
                    time1 = time.time()
                    outport = self._ip_hashing(ip_src, ip_dst, self.spine_num) + 1 # +1 because port 0 is for controller connection
                    self.lb_time += time.time()-time1
                print 'Packet (', ip_src, ip_dst ,') in', dpid, '->',outport
        # Forward current packet
        self.forward_packet(datapath, msg, outport)
        # Create new flow rule to avoid same packet forwarded into controller in future
        self.mod_host_flow(datapath, ip_src, ip_dst, outport)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocols(ethernet.ethernet)[0]
        if eth_pkt.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return
        dpid = datapath.id
        outport = 0
        if len(pkt.get_protocols(ipv4.ipv4))>0 :
            ip4_pkt = pkt.get_protocols(ipv4.ipv4)[0]
            host_src = ip4_pkt.src
            host_dst = ip4_pkt.dst
        if len(pkt.get_protocols(arp.arp))>0:
            arp_pkt = pkt.get_protocols(arp.arp)[0]
            ip_src = arp_pkt.src_ip
            ip_dst = arp_pkt.dst_ip
            self._find_route(datapath, ip_src, ip_dst, msg)
        if outport>0:
            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data
            actions = [parser.OFPActionOutput(outport)]
            out = parser.OFPPacketOut(datapath=datapath, in_port=in_port, actions=actions, data=data, buffer_id=msg.buffer_id)
            datapath.send_msg(out)