import socket
import time
import string

from faradayio import faraday
from tests.serialtestclass import SerialTestClass
from scapy.all import UDP, IP, sendp


def test_tunSetup():
    """Setup a Faraday TUN and check initialized values"""
    faradayTUN = faraday.TunnelServer()

    # Check defaults
    assert faradayTUN._tun.name == 'Faraday'
    assert faradayTUN._tun.addr == '10.0.0.1'
    assert faradayTUN._tun.netmask == '255.255.255.0'
    assert faradayTUN._tun.mtu == 1500


def test_tunSend():
    """
    Start a TUN adapter and send a message through it. This tests sending ascii
    over a socket connection through the TUN while using pytun to receive the
    data and check that the IP payload is valid with scapy.
    """
    # Start a TUN adapter
    faradayTUN = faraday.TunnelServer()

    # Send a string throught the IP
    HOST = "10.0.0.2"
    PORT = 9999  # Anything

    # Just send asci lprintable data for now
    msg = bytes(string.printable, "utf-8")

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((HOST, PORT))
    s.send(msg)
    s.close()

    # Loop through packets received until packet is received from correct port
    while True:
        data = faradayTUN._tun.read(faradayTUN._tun.mtu)

        try:
            if(IP(data[4:]).dport == PORT):
                # print(IP(data[4:]).show())
                break

        except AttributeError as error:
            pass
            # AttributeError was encountered
            # Tends to happen when no dport is in the packet
            # print("AttributeError")

    # Remove the first four bytes from the data since there is an ethertype
    # header that should not be there from pytun
    payload = IP(data[4:]).load

    # Check that slip message was sent correctly over TunnelServer
    assert msg == payload


def test_tunSlipSend():
    """
    Test SLIP data sent over the TUN adapter and serial port.

    Start a TUN adapter and send data over it while a thread runs to receive
    data sent over the tunnel and promptly send it over a serial port which is
    running a serial loopback test. Ensures data at the end of the loopback
    test is valid when received over serial. This test does not cover serial
    to TUN/IP nor IP to TUN data validation.
    """
    # Create a test serial port
    serialPort = SerialTestClass()

    # Configure the TUN adapter and socket port we aim to use to send data on
    sourceHost = '10.0.0.1'  # IP of the TUN adapter
    sourcePort = 9998
    destHost = '10.0.0.2'
    destPort = 9999

    # Start the monitor
    TUNMonitor = faraday.Monitor(serialPort=serialPort,
                                 name="Faraday",
                                 addr=sourceHost,
                                 mtu=1500)

    srcPacket = (IP(dst=destHost,
                    src=sourceHost) /
                 UDP(sport=sourcePort,
                 dport=destPort) / "Hello, world!").__bytes__()

    # Use scapy to send packet over Faraday
    sendp(srcPacket, iface="Faraday")

    # Manually check TUN adapter for packets in the tunnel
    # This is necessary because the threads are not running
    while True:
        # Loop through packets until correct packet is returned
        packet = TUNMonitor.checkTUN()
        if packet:
            # Strip etherType off of IP packet
            ipPacketSerialTX = packet[4:]
            if IP(ipPacketSerialTX).dst == destHost:
                # Check that packet got through TUN without error
                break
    # Obtained IP packet to destination IP so check that it hasn't changed
    assert ipPacketSerialTX == srcPacket

    # Manually send IP packet over serial port including etherType.
    bytesSent = TUNMonitor.txSerial(packet)
    assert bytesSent is not None    # We expect some data sent
    assert bytesSent > len(packet)  # We expect SLIP encoding to add bytes

    # Receive data over serial port and check packets for test IP packet
    rxBytes = TUNMonitor.rxSerial(TUNMonitor._TUN._tun.mtu)
    for item in rxBytes:
        ipPacketSerialRX = item[4:]
        # Iterate through packets and check for packet to destination IP
        if IP(ipPacketSerialRX).dst == destHost:
            # Found IP packet to destination so break from loop
            break

    # Check that the packet received over the serial loopback == same as sent
    assert ipPacketSerialRX == ipPacketSerialTX


def test_serialToTUN():
    """
    Test serial port to TUN link. Don't need a serial port but just assume that
    an IP packet was received from the serial port and properly decoded with
    SLIP. Send it to the TUN and verify that the IP:PORT receives the message.
    """
    # Create a test serial port for TUN Monitor class. Won't be used.
    serialPort = SerialTestClass()

    # Configure TUN IP:PORT and IP Packet source IP:PORT parameters for test
    sourceAddress = '10.0.0.2'
    sourcePort = 9998
    tunAddress = '10.0.0.1'
    tunPort = 9999

    # Start a TUN Monitor class
    TUNMonitor = faraday.Monitor(serialPort=serialPort,
                                 name="Faraday",
                                 addr=tunAddress,
                                 mtu=1500)

    # Open a socket for UDP packets and bind it to the TUN address:port
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('10.0.0.1', 9999))

    # Create simple IP packet with message. Send to TUN address:port
    message = bytes("Hello, World! {0}".format(time.time()), "utf-8")
    etherType = b"\x00\x00\x08\x00"
    packet = etherType + (IP(dst=tunAddress,
                             src=sourceAddress) /
                          UDP(sport=sourcePort,
                              dport=tunPort)/message).__bytes__()

    # Write a simple message over the TUN, no need for checker thread
    TUNMonitor._TUN._tun.write(packet)

    # Receive data from the socket bound to the TUN address:port
    data, address = s.recvfrom(4096)

    # Check that data written to TUN matches data received from socket
    assert data == message

    # Close the socket
    s.close()
