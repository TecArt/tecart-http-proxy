# tecart-http-proxy

:heavy_exclamation_mark: This project is not under active development anymore. We would encourage you to use another proxy server like [tinyproxy](https://github.com/tinyproxy/tinyproxy).

This is a HTTP proxy server that supports CONNECT requests. The proxy uses a
DNS cache that allows for clean retries when multiple IPs are returned for 

## Installation
### Prerequisites

The recommended way to run in production is daemonization with `systemd` unit file which available at `contrib/tecart-http-proxy.service`.

You will also need Python 3 with Pip and venv installed.

For Debian, the following command will install the prerequisites:

```sh
apt-get install python3 python3-dev python3-pip python3-venv
```
If you are using Ubuntu, you need to enable multiverse repos as well. 

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

python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
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
