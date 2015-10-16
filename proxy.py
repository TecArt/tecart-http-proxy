#!/usr/bin/env python2
"""
HTTP proxy server that supports CONNECT requests and adds support for 
DNS caching.

Copyright (c) 2015 TecArt GmbH. All rights reserved.

This source code is licensed under the license found in the LICENSE file
in the root directory of this source tree.
"""

import argparse
import urlparse

import twisted.web.http
import twisted.internet
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import address, error
from twisted.internet.endpoints import HostnameEndpoint 
from twisted.web.proxy import Proxy, ProxyRequest
from twisted.python import log, syslog
from dnscache import DnsCache

import config

class ConnectProxyRequest(ProxyRequest):
    """ConnectProxyRequest is a factory for for HTTP proxy requests
    that supports the "CONNECT" keyword for tunneling of
    SSL/TLS-enabled connections.
    
    @ivar connectedProtocol: 
    @ivar noisy: Controls whether this class will emit debug noise
    """

    connectedProtocol = None
    noisy = False

    def process(self):
        """Checkes the request for the CONNECT keyword and redirects
        to specific functions accordingly."""

        if self.method == 'CONNECT':
            self.process_connect()
        else:
            ProxyRequest.process(self)

    def fail(self, message, body):
        """Returns the HTTP 501 status code if an error occurs
        
        @param message: Short description that will be appended to the
                        HTTP status code
        @type message: str

        @param body: The error full message that will be send to the
                     user
        @type body: str
        """
        self.setResponseCode(501, message)
        self.responseHeaders.addRawHeader("Content-Type", "text/html")
        self.write(body)
        self.finish()

    def split_hostport(self, hostport, port=443):
        """Splits the host and port that where received and sets a
        default port if non was submitted

        @param hostport: String containing host and port
        @type hostport: str

        @param port: The default port that is used if hostport contains
                     no port
        @type port: int

        @return: A tuple containing host and port
        """
        parts = hostport.split(':', 1)
        if len(parts) == 2:
            try:
                port = int(parts[1])
            except ValueError:
                pass
        return parts[0], port

    def process_connect(self):
        """Process a client CONNECT request and connect the requested
        server with the client.
        """
        parsed = urlparse.urlparse(self.uri)
        default_port = self.ports.get(parsed.scheme)

        host, port = self.split_hostport(parsed.netloc or parsed.path,
                                        default_port)
        if port is None:
            self.fail("Bad CONNECT Request",
                      "Unable to parse port from URI: %s" % repr(self.uri))
            return

        clientFactory = ConnectProxyProtocolFactory(host, port, self)
        clientFactory.noisy = False
        self.ip = self.reactor.dns_cache.get(host, port)
        self.reactor.connectTCP(self.ip, port, clientFactory,
                timeout=config.REQUEST_TIMEOUT)


class ConnectProxy(Proxy):
    """Twisted protocol that can process HTTP proxy requests with and 
    without the CONNECT keyword
    
    @ivar requestFactory: L{ConnectProxyRequest} for the request to the
                          remote the client requested
    @ivar connectedRemote: C{None} or the remote the client connects to
    @ivar noisy: Controls whether this class will emit debug noise
    """

    requestFactory = ConnectProxyRequest
    connectedRemote = None
    noisy = False

    def requestDone(self, request):
        """requestDone Fires when the first client request is done.

        @param request: The finished request from a client
        @type request: 
        """
        if request.method == 'CONNECT' and self.connectedRemote is not None:
            self.connectedRemote.connectedClient = self
        else:
            Proxy.requestDone(self, request)

    def connectionLost(self, reason):
        """Fired after a connection is closed or lost. Calls
        loseConnection() on the transport as well.
        
        @param reason: Holds the reason, why the connection was lost
        """
        if self.connectedRemote is not None:
            self.connectedRemote.transport.loseConnection()
        Proxy.connectionLost(self, reason)

    def dataReceived(self, data):
        """Fires when data is received from the remote. If a CONNECT 
        request was issued, the data is sent directly to the client, 
        else it will be processed by the Proxy class from Twisted.
        
        @param data: Data received from the remote
        """
        if self.connectedRemote is None:
            Proxy.dataReceived(self, data)
        else:
            # Once proxy is connected, forward all bytes received
            # from the original client to the remote server.
            self.connectedRemote.transport.write(data)


class ConnectProxyProtocol(Protocol):
    """Protocol that connects to a proxy client, client meaning the 
    user who will request HTTP ressources.
    
    @ivar connectedClient: Object holding the transport and other client 
                           information
    @ivar noisy: Controls whether this class will emit debug noise
    """

    connectedClient = None
    noisy = False

    def connectionMade(self):
        """Fires, when a client connects to the proxy server. The 
        method will set appropriate headers to let the client to it can
        continue with it's CONNECTed channel."""

        try:
            self.factory.request.channel.connectedRemote = self
            self.factory.request.setResponseCode(200, "CONNECT OK")
            self.factory.request.setHeader('X-Connected-IP',
                                           self.transport.realAddress[0])
            self.factory.request.setHeader('Content-Length', '0')
            self.factory.request.finish()
        except:
            pass

    def connectionLost(self, reason):
        """Fires, when the connection to the client is lost or closed.
        
        Will close the transport connection to the client, if the client
        object is still available.
        """

        if self.connectedClient is not None:
            self.connectedClient.transport.loseConnection()

    def dataReceived(self, data):
        """Fired, when data from the client is received. Will 
        pass-through the data for CONNECTed ends, if a connection is
        present"""

        if self.connectedClient is not None:
            # Forward all bytes from the remote server back to the
            # original connected client
            self.connectedClient.transport.write(data)


class ConnectProxyProtocolFactory(ClientFactory):
    """Factory for L{ConnectProxyProtocol} objects
    
    @ivar protocol: Used protocol for connections. L{ConnectProxyProtocol}
    @ivar retries: How many times a connection will time out before the
                   server will give up
    @ivar noisy: Controls whether this class will emit debug noise
    """

    protocol = ConnectProxyProtocol
    retries = 5
    noisy = False

    def __init__(self, host, port, request):
        """Creates an instance of L{ConnectProxyProtocolFactory}
        
        @param host: Hostname of the server to connect to
        @type host: str

        @param port: Port of the server to connect to
        @type port: int

        @param request: A request object containing information what the
                        client requested
        """

        self.request = request
        self.host = host
        self.port = port

    def clientConnectionFailed(self, connector, reason):
        """Fires when the connection was lost during a connection 
        attempt to the external ressource. If the reason for the failed
        connection was a timeout, the server will try a reconnect. 

        @param connector: The twisted Connector object
        @type connector: L{twisted.internet.tcp.Connector}

        @param reason: The reason for the failed connection
        """
        if reason.check(error.TimeoutError) or reason.check(error.ConnectError):
            twisted.internet.reactor.dns_cache.mark_hostport_down(self.host,
                    self.request.ip, self.port)

            if self.retries > 0:
                self.retries -= 1
                connector.host = twisted.internet.reactor.dns_cache.get(
                        self.host, self.port)
                connector.connect()
                return
        self.request.fail("Gateway Error", str(reason))


class ProxyFactory(twisted.web.http.HTTPFactory):
    protocol = ConnectProxy
    noisy = False


if __name__ == '__main__':
    import sys

    if config.LOG_TYPE is 'syslog':
        syslog.startLogging(prefix='tecproxy', facility=config.LOG_FACILITY)
    else:
        log.startLogging(sys.stderr)

    factory = ProxyFactory()

    twisted.internet.reactor.dns_cache = DnsCache(ttl=config.DNS_TTL)
    twisted.internet.reactor.listenTCP(config.LISTEN_PORT, factory)
    twisted.internet.reactor.run()
