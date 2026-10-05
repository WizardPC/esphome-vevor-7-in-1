#!/usr/bin/env python3
"""La carte est-elle joignable en API native (pour verifier le binaire) ?"""
import socket, os, re
H = "172.16.0.205"
try:
    with socket.create_connection((H, 6053), timeout=6) as s:
        print("port 6053 ouvert")
except Exception as e:
    print("port 6053 :", e)
try:
    with socket.create_connection((H, 80), timeout=6) as s:
        print("port 80 ouvert")
except Exception as e:
    print("port 80 :", e)
import subprocess
print(subprocess.run(["grep", "-c", "api", "/home/hermes/projets/vevor-7in1/esphome/secrets.yaml"],
                     capture_output=True, text=True).stdout.strip(), "lignes contenant 'api'")
