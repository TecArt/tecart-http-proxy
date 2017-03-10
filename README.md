# tecart-http-proxy

This is a HTTP proxy server that supports CONNECT requests. The proxy uses a
DNS cache that allows for clean retries when multiple IPs are returned for 

## Installation
### Prerequisites

The server has been tested with `supervisor` as helper for daemonization. This 
is the recommended way to run in production.

You will also need Python 3 with Pip and venv installed.

For Debian, the following command will install the prerequisites:

```sh
apt-get install python3 python3-dev python3-pip python3-venv supervisor
```

### Software installation

To retrieve the code, download and unpack the 
[latest releases](https://github.com/TecArt/tecart-http-proxy/releases/latest) 
to a directory of your choice. 

```sh
mkdir -p /opt/TecArt/
cd /opt/TecArt

release=$(curl -s https://api.github.com/repos/TecArt/tecart-http-proxy/releases/latest | grep zipball_url | head -n 1 | cut -d '"' -f 4)
curl -L -o tecart-http-proxy.zip "$release"
unzip tecart-http-proxy.zip
rm tecart-http-proxy.zip
mv TecArt-tecart-http-proxy-*/ tecart-http-proxy/

cd tecart-http-proxy/

pyvenv env
source env/bin/activate
pip install -r requirements.txt
```

### Supervisor configuration

To daemonize the tecart-http-proxy, create a supervisor configuration under 
`/etc/supervisor/conf.d/tecart-http-proxy.conf` with the following content:

```ini
[program:tecart-http-proxy]
command=/opt/TecArt/tecart-http-proxy/env/bin/python /opt/TecArt/tecart-http-proxy/proxy.py
user=proxy
```

After creating the configuration, restart the supervisor with the following
command:

```sh
service supervisor restart
```

### Systemd configuration

To use the tecart-http-proxy with systemd, simply copy the unit file to your
system directory:

```sh
cp /opt/TecArt/tecart-http-proxy/contrib/tecart-http-proxy.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable tecart-http-proxy
systemctl start tecart-http-proxy
```
