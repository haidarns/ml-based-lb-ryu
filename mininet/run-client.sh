#!/bin/bash
ITGSend -l ./log_voip/client_voip.log -a 10.0.0.2 -t 200000 -rp 1001 VoIP -x G.711.2 -h RTP -VAD &