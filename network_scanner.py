#!/usr/bin/env python3

from scapy.all import arping

def scan(ip_range: str):
    try:
        responses, _ = arping(ip_range, verbose=False)
    except PermissionError:
        print("Need root to arp scan")
        return []

    devices = []
    for response in responses:
        ip = response.answer.psrc
        mac = response.answer.src

        devices.append({
            "ip": ip,
            "mac": mac,
        })

    return devices

def find_ip_by_mac(ip_range: str, mac: str):
    for device in scan(ip_range):
        if device["mac"].upper() == mac.upper():
            return device["ip"]
    return None
