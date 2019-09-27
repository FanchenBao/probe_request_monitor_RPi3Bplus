#!/bin/bash

main() {
    # continuously checking for any data file to upload in the background
    source venv/bin/activate
    python3 upload_s3.py -p $PERIOD &
    UPLOAD_PID=$!
    echo "Upload begins in the background..."

    # enable monitor mode if it hasn't been turned on already
    NUM_MON0=`iwconfig | grep mon0 | wc -l`
    if [[ "$NUM_MON0" -lt "1" ]]; then
        sudo iw phy `iw dev wlan0 info | gawk '/wiphy/ {printf "phy" $2}'` interface add mon0 type monitor
    fi
 
    sudo ifconfig mon0 up  # turn on monitor mode. No need to turn it off.

    # run sniff-probes in the background, so that we can terminate it periodically
    while true; do
        ./run_mon.sh &
        MON_PID=$!
        sleep $PERIOD
        kill $MON_PID
	mv sniff-probes/*.txt data/  # move data file into its own storage place for further process

	#python3  email/send_email.py  # to send email (not needed, cuz eventually we shall upload data to cloud)
    done
}

cleanup() {
    if [[ "$UPLOAD_PID" -ne 0 ]]; then
        kill $UPLOAD_PID
    fi
    sudo ifconfig mon0 down  # turn down monitor mode
    deactivate
}

print_usage() {
    printf "Usage: start_up.sh [-p] <period> [-h]\n-p\tPeriod (i.e. duration in time) for each monitoring session (in seconds). Default period is 60 s.\n-h\tShow this usage message.\n" 
}

# Defaults
PERIOD=60  # default monitoring session set to 60 seconds

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -p)
      if [[ "$2" != "" ]]; then
        PERIOD="$2"
        shift 1
      else # -p must be followed by a second argument
        print_usage
        exit 1
      fi
      shift 1
      ;;
    -h)
      print_usage
      exit 1
      ;;
    *) # unsupported flags
      print_usage
      exit 1
      ;;
  esac
done

# clean up after exit
trap cleanup EXIT

main
