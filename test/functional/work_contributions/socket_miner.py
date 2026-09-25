#!/usr/bin/env python3
"""Socket-only mining client: reconstruct actual Stratum jobs, hash, submit nonce fields.
Operator RPC sets local transactions; client never sends coinbase, templates, proofs or full blocks.
"""
# Copyright (c) 2026 The Bitcoin developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.
from pathlib import Path
import hashlib,io,json,socket,struct,sys,tempfile,time
ROOT=Path(__file__).resolve().parent
import native_checks as n
from test_framework.messages import hash256,uint256_from_compact

class Miner:
    def __init__(self,port):
        self.socket=socket.create_connection(('127.0.0.1',port),timeout=4)
        self.file=self.socket.makefile('rb');self.sequence=0;self.job=None;self.extra=None;self.trace=[]
    def receive(self):
        raw=self.file.readline()
        if not raw:raise RuntimeError('endpoint closed')
        msg=json.loads(raw);self.trace.append({'receive':msg})
        if msg.get('method')=='mining.notify':self.job=msg['params']
        return msg
    def request(self,method,params,fragment=False):
        self.sequence+=1;msg={'id':self.sequence,'method':method,'params':params};self.trace.append({'send':msg})
        raw=(json.dumps(msg)+'\n').encode()
        if fragment:self.socket.sendall(raw[:7]);self.socket.sendall(raw[7:])
        else:self.socket.sendall(raw)
        while True:
            response=self.receive()
            if response.get('id')==self.sequence:return response
    def login(self):
        response=self.request('mining.subscribe',[],True);self.extra=response['result'][1]
        assert response['result'][2]==4
        response=self.request('mining.authorize',['fixture.worker','']);assert response['result'] is True
        while self.job is None:self.receive()
    def nextjob(self,old):
        while self.job is None or self.job[0]==old:self.receive()
        return self.job
    def find(self,full=False):
        job=self.job;extra2='00000000'
        raw=bytes.fromhex(job[2]+self.extra+extra2+job[3]);root=hash256(raw)
        for sibling in job[4]:root=hash256(root+bytes.fromhex(sibling))
        wireprev=bytes.fromhex(job[1]);prev=b''.join(wireprev[i:i+4][::-1] for i in range(0,32,4))
        target=uint256_from_compact(int(job[6],16));prefix=struct.pack('<I',int(job[5],16))+prev+root+struct.pack('<II',int(job[7],16),int(job[6],16))
        for nonce in range(10000):
            header=prefix+struct.pack('<I',nonce);digest=hash256(header)
            if (int.from_bytes(digest,'little')<=target)==full:
                return ['fixture.worker',job[0],extra2,job[7],f'{nonce:08x}'],digest[::-1].hex(),raw
        raise AssertionError('unexpected easy-target search exhaustion')
    def close(self):self.file.close();self.socket.close()
