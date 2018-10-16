#!/bin/bash
sudo python ./ta_topo.py $1 $2 1 voip && cd test_voip
./get_voip_data.sh $1 $2 && cd ..
