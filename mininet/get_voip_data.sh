#!/bin/bash
ITGDec ./log_voip/server_voip.log -f t -c 1000 ./log_voip/server_voip.txt
mv ./log_voip/server_voip.txt ./result/scenario_$1_$2_$3_voip_$4.txt