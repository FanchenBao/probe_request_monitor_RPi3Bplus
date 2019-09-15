#!/bin/bash
cd sniff-probes
if [ `ls -1 *.txt 2>/dev/null | wc -l` -ne 0 ]; then  # check whether any unmoved data still exists. If they do, move them to storage place
    mv *.txt ../data
fi
sudo IFACE=mon0 OUTPUT="$(date '+%F_%T').txt" ./sniff-probes.sh >> monitor.log 2>&1
