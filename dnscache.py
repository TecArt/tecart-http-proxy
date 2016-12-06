"""
A DNS class that takes the connected port into account and uses caching
and background checks to look for offline IP/port combinations,
especially when the DNS record returns multiple IPs(Round-Robin).

Copyright (c) 2015 TecArt GmbH.  All rights reserved.

This source code is licensed under the license found in the LICENSE file
in the root directory of this source tree.
"""

import syslog
import logging
import socket

from random import choice
from time import time
from twisted.python import log
from twisted.internet import defer, reactor
from twisted.internet.threads import deferToThread
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.protocols.policies import TimeoutMixin

import config

class NoopProtocol(Protocol, TimeoutMixin):
    """Protocol that disconnects directly after connecting"""

    noisy = False

    def __init__(self, dns_cache, host, ip, port, timeout):
        """Construct a new NoopProtocol.

        @param dns_cache: An instance of DnsCache
        @type dns_cache: DnsCache

        @param host: Hostname of the server
        @type host: str

        @param str ip: IP of the server
        @type ip: str

        @param port: Port of the server
        @type port: int

        @param timeout: Time in seconds after which a connection attempt will 
                        be aborted
        @type timeout: int
        """
        self.dns_cache = dns_cache
        self.host = host
        self.ip = ip
        self.port = port

        self.setTimeout(timeout)

    def connectionMade(self):
        """Fires when a connection was established. Stops the timeout timer and
        closes the connection on the transport"""
        self.setTimeout(None)
        self.transport.loseConnection()


class NoopFactory(ClientFactory):
    """Client factory for NoopClients"""

    noisy = False

    def __init__(self, dns_cache, host, ip, port, timeout=1):
        """Construct a new NoopFactory
        
        @param dns_cache: An instance of DnsCache
        @type dns_cache: DnsCache

        @param host: Hostname of the server
        @type host: str

        @param str ip: IP of the server
        @type ip: str

        @param port: Port of the server
        @type port: int

        @param timeout: Time in seconds after which a connection attempt will 
                        be aborted
        @type port: int
        """
        self.dns_cache = dns_cache
        self.host = host
        self.ip = ip
        self.port = port
        self.timeout = timeout

    def buildProtocol(self, addr):
        """Creates and returns a NoopProtocol object

        @param addr: Unused

        @return: A L{NoopProtocol} instance wired up to L{DnsCache}
        """
        return NoopProtocol(self.dns_cache, self.host, self.ip, self.port,
                self.timeout)


class DnsCache:
    """DNS Cache for Python with port awareness and background checking of 
    already used host-port cominations.
    
    @ivar lookup_table: The in-memory cache for the DNS cache
    @ivar ipv6_enabled: Boolean that is true if IPv6 support was detected
    @ivar cron: Stores the LoopingCall for garbage collection or C{None}
    """

    lookup_table = {}
    ipv6_enabled = True
    cron = None


    def __init__(self, ttl=3600):
        """Creates a new L{DnsCache} instance. Will check if IPv6 is possible
        and set the ipv6_enabled flag accordingly.
        
        @param ttl: The longest time without any access a cache entry will be
                    held in-memory before it is removed
        @type ttl: int
        """

        self.ttl = ttl

        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.setblocking(1)
        try:
            s.connect(('ipv6.google.com', 0))
        except:
            self.ipv6_enabled = False


    def get(self, host, port=0):
        """Returns an IP for the specified host and port. If the host/port 
        combination is not already in the cache, it will store it.
        
        @param host: The hostname to lookup
        @type host: str
        
        @param port: The port number that is accessed
        @type port: int
        """

        if not self.cron:
            # Setup cron for garbage collection
            from twisted.internet import task

            self.cron = task.LoopingCall(self._garbage_collect)
            self.cron.start(config.DNS_GARBAGE_LOOP_TIME)

        lookup_name = (host, port)
        if lookup_name not in self.lookup_table:
            self.lookup_table[lookup_name] = {}

            for records in socket.getaddrinfo(host, port):
                if len(records[-1]) > 2 and not self.ipv6_enabled:
                    continue

                ip = records[-1][0]
                if not ip:
                    del self.lookup_table[lookup_name]
                    raise Exception(
                        "No IP records found in record set %s" % records)

                if ip not in self.lookup_table[lookup_name]:
                    self.lookup_table[lookup_name][ip] = time()

        
        ip = choice(self.lookup_table[lookup_name].keys())
        self.lookup_table[lookup_name][ip] = time()

        return ip


    def mark_hostport_down(self, host, ip, port):
        """Removes a host/port combination from the cache.

        @param host: The hostname of the server
        @type host: str

        @param ip: The ip of the server
        @type ip: str

        @param port: The port of the server
        @type port: int
        """

        log.msg("Removing <%s> %s:%s from cache" % (host, ip, port),
                logLevel=logging.DEBUG, syslogPriority=syslog.LOG_DEBUG)
        lookup_name = (host, port)
        try:
            del self.lookup_table[lookup_name][ip]

            if len(self.lookup_table[lookup_name]) < 1:
                del self.lookup_table[lookup_name]
        except:
            pass


    def _garbage_collect(self):
        """Garbage collection method that will be called periodically by a 
        LoopingCall. Cleans up old entries from the cache and re-checks old 
        entries to see if IPs changed or are (un)available."""

        log.msg("DnsCache::_garbage_collect()", logLevel=logging.DEBUG,
                syslogPriority=syslog.LOG_DEBUG)
        log.msg(self.lookup_table, logLevel=logging.DEBUG,
                syslogPriority=syslog.LOG_DEBUG)
        
        d = []

        for host, port in self.lookup_table.keys():
            lookup_name = (host, port)

            for record in self.lookup_table[lookup_name].keys():
                record_time = self.lookup_table[lookup_name][record]
                if record_time < (time() - self.ttl):
                    log.msg("Removing old record %s" % record, logLevel=logging.DEBUG,
                            syslogPriority=syslog.LOG_DEBUG)
                    del self.lookup_table[lookup_name][record]

            # clean up & continue to next entry if all records have been remove
            if len(self.lookup_table[lookup_name]) < 1:
                del self.lookup_table[lookup_name]
                continue

            for records in socket.getaddrinfo(host, port):
                af, socktype, proto, canconname, sa = records

                # We only need TCP streams for HTTP(S)
                if socktype is not socket.SOCK_STREAM:
                    continue

                # Only check IPv6 if it's available
                if len(records[-1]) is 4 and not self.ipv6_enabled:
                    continue

                try:
                    p = { 'sa': sa, 'host': host, 'self': self }

                    point = TCP4ClientEndpoint(reactor, p['sa'][0], p['sa'][1], timeout=5)

                    def deferFunc (q=p, point=point):
                        c = point.connect(NoopFactory(q['self'], q['host'], 
                            q['sa'][0], q['sa'][1], config.DNS_TEST_TIMEOUT))
                        c.addErrback(lambda _, q=q: self.mark_hostport_down(
                            ip=q['sa'][0], port=q['sa'][1], host=q['host']))

                    d += [ deferToThread(deferFunc) ]
                except:
                    pass
