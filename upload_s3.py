from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient
from AWSIoTPythonSDK.exception.AWSIoTExceptions import publishQueueDisabledException
import time
import json
import glob
import logging
import os
import sys
import getopt
import http.client as httplib
import multiprocessing
import signal


def parseCommandLine(argv):
    helpmsg = """usage: upload_s3.py [-p] <period>
-p\tHow often to check data storage for data upload (in seconds). Default to every 60 s.
"""
    try:
        opts, args = getopt.getopt(argv, "p:")
    except getopt.GetoptError:
        print(helpmsg)
        sys.exit(2)

    PERIOD = 60
    for opt, arg in opts:
        if opt == '-p':
            if arg.isdigit():  # argument must be of digit
                PERIOD = int(arg)
            else:
                print(helpmsg)
                sys.exit()
    return PERIOD


def internet_on():  # borrowed from https://stackoverflow.com/a/29854274/9723036
    conn = httplib.HTTPConnection("www.google.com", timeout=5)
    try:
        conn.request("HEAD", "/")
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


class UploadService():
    """ Exclusively handle logic for uploading file to aws s3. The actual
        function for uploading will be run as a child process, which allows
        the parent process to constantly monitor internet connection and start
        or terminate uploading as needed. The inclusion of signal_handler()
        allows uploading to terminate if the parent process is terminated by
        upstream script.
    """

    def __init__(self, logger, PERIOD):
        self.logger = logger
        self.PERIOD = PERIOD
        self.p = multiprocessing.Process(target=self.send_MQTT)
        signal.signal(signal.SIGTERM, self.sigterm_handler)  # handle SIGTERM event

    def sigterm_handler(self, signal, frame):
        """ This is to ensure when upload_s3 gets terminated by SIGTERM in the
            over all shell script, the send_MQTT process gets pulled down as well
        """
        if self.p.is_alive():
            self.p.kill()
            self.p.join()
            self.logger.info('Uploading ends due to parent process terminated.')
        sys.exit(0)

    def send_MQTT(self):
        # A random programmatic shadow client ID.
        SHADOW_CLIENT = "myShadowClient"

        # The unique hostname that &IoT; generated for
        # this device.
        HOST_NAME = "a2jj5oc6iwavb-ats.iot.us-east-2.amazonaws.com"

        # The relative path to the correct root CA file for &IoT;,
        # which you have already saved onto this device.
        KEY_DIR = './keys/'
        ROOT_CA = KEY_DIR + "AmazonRootCA1.pem"

        # The relative path to your private key file that
        # &IoT; generated for this device, which you
        # have already saved onto this device.
        PRIVATE_KEY = KEY_DIR + "81b1962352-private.pem.key"

        # The relative path to your certificate file that
        # &IoT; generated for this device, which you
        # have already saved onto this device.
        CERT_FILE = KEY_DIR + "81b1962352-certificate.pem.crt"

        # A programmatic shadow handler name prefix.
        SHADOW_HANDLER = "RPi_3Bplus_WPB_test"

        # Create, configure, and connect a shadow client.
        myShadowClient = AWSIoTMQTTShadowClient(SHADOW_CLIENT)
        myShadowClient.configureEndpoint(HOST_NAME, 8883)
        myShadowClient.configureCredentials(ROOT_CA, PRIVATE_KEY, CERT_FILE)
        myShadowClient.configureConnectDisconnectTimeout(10)
        myShadowClient.configureMQTTOperationTimeout(5)
        myShadowClient.connect()

        # Create a programmatic representation of the shadow.
        myDeviceShadow = myShadowClient.createShadowHandlerWithName(SHADOW_HANDLER, True)

        class CallBack():
            """ Use a class to capture call back info, especially response status """

            def __init__(self, logger):
                self.response_status = ""
                self.logger = logger

            def myShadowUpdateCallback(self, payload, responseStatus, token):
                msg = f'UPDATE: $aws/things/{SHADOW_HANDLER}/shadow/update/#\n\
                    payload = {payload}\n\
                    responseStatus = {responseStatus}\n\
                    token = {token}\n'
                self.logger.info(msg)
                self.response_status = responseStatus

        # For call back purpose
        cb = CallBack(self.logger)

        # This is an infinite loop. It keeps checking whether a new txt file is in
        # data directory. If there is one, we upload it to s3 bucket
        while True:
            txt_files = [f for f in glob.glob('./data/*.txt')]
            for file in txt_files:
                data = "timestamp,mac\n"
                # have to use shrunk_data, because test_data is too big for MQTT message.
                with open(file) as f_obj:
                    for line in f_obj:
                        line_lst = line.split(' ')
                        data += ','.join([line_lst[0], line_lst[2]]) + '\n'
                msg = {'state': {'reported': {'timestamp': file.split('/')[-1][:-4], 'data': data}}}
                try:  # offline request queue is not enabled for shadow client. Thus this exception has to be avoided, and this won't produce harmful side effect.
                    myDeviceShadow.shadowUpdate(json.dumps(msg), cb.myShadowUpdateCallback, 5)
                except publishQueueDisabledException:
                    self.logger.error("Offline request queue disabled by default for shadow device")
                time.sleep(5)  # do not overwhelm connection to aws iot

                # remove the file once it is successfully uploaded to s3
                # Any other status, e.g. 'rejected', 'timeout', etc., we do not remove
                # the file and check the log later for detailed info.
                if cb.response_status == 'accepted':
                    os.remove(file)
            time.sleep(self.PERIOD)  # check for new txt files based on the frequency of data file production


def main(argv):
    # set up logger
    logging.basicConfig(filename='transmit.log')
    logger = logging.getLogger("AWSIoTPythonSDK.core")
    logger.setLevel(logging.INFO)
    streamHandler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    streamHandler.setFormatter(formatter)
    logger.addHandler(streamHandler)

    PERIOD = parseCommandLine(argv)

    # Outer infinity loop, constantly checking for internet connection.
    # Inner infinity loop (within send_MQTT) for constantly checking new data file and uploading
    uploading = False
    while True:
        if internet_on():
            if not uploading:  # internet on but not uploading, spawn uploading service
                logger.info('Internect connection ON.')
                # Must spawn a new process each time. Cannot kill a process and
                # start the same process again, because that triggers "cannot
                # start a process twice" exception.
                upload_service = UploadService(logger, PERIOD)
                upload_service.p.start()
                uploading = True
        else:
            if uploading:  # internet off but still uploading, terminate uploading
                upload_service.p.kill()
                upload_service.p.join()
                logger.info('Internet connection is down. Uploading terminated.')
                uploading = False
            else:
                logger.warning('Internet connection is still DOWN. Retry in 10 seconds.')
        time.sleep(10)  # checking internet connection every 10 seconds


if __name__ == '__main__':
    main(sys.argv[1:])
