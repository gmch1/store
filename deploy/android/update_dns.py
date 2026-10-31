"""Maintain explicitly owned AAAA records directly from the Android host."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class DNSUpdateError(RuntimeError):
    pass


def candidates(interfaces):
    result = []
    for interface in interfaces:
        for item in interface.get('addr_info', []):
            address = ipaddress.ip_address(item['local'])
            if address.version != 6 or address not in ipaddress.ip_network('2000::/3'):
                continue
            if item.get('prefixlen') != 64 or item.get('preferred_life_time', 1) == 0:
                continue
            flags = item.get('flags', [])
            if any(item.get(flag, False) or flag in flags
                   for flag in ('deprecated', 'temporary', 'tentative', 'dadfailed')):
                continue
            result.append((item.get('preferred_life_time', 0), str(address)))
    return [address for _, address in sorted(result, reverse=True)]


def current_address(interface):
    interfaces = json.loads(subprocess.check_output(
        ['ip', '-j', '-6', 'addr', 'show', 'dev', interface], text=True, timeout=5))
    for address in candidates(interfaces):
        probe = subprocess.run(['curl', '--noproxy', '*', '-6', '--interface', address,
                                '--connect-timeout', '3', '--max-time', '8', '-fsS',
                                'https://api.cloudflare.com/client/v4/ips'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if probe.returncode == 0:
            return address
    raise DNSUpdateError('No reachable preferred public /64 IPv6 address')


class Cloudflare:
    def __init__(self, zone_id, token_file):
        if not re.fullmatch(r'[a-f0-9]{16,64}', zone_id):
            raise DNSUpdateError('Invalid configured DNS zone ID')
        self.base = 'https://api.cloudflare.com/client/v4/zones/' + zone_id + '/dns_records'
        self.token = Path(token_file).read_text().strip()
        if not self.token:
            raise DNSUpdateError('DNS credential is empty')

    def request(self, method, suffix='', payload=None):
        request = urllib.request.Request(self.base + suffix, method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # Never log credentials, headers, or unfiltered provider error responses.
            raise DNSUpdateError(f'DNS API returned HTTP {exc.code}') from None
        except urllib.error.URLError:
            raise DNSUpdateError('DNS API connection failed') from None
        if not result.get('success'):
            raise DNSUpdateError('DNS API rejected the operation')
        return result['result']

    def records(self, name):
        return self.request('GET', '?' + urllib.parse.urlencode({'name': name, 'per_page': 100}))

    def create(self, payload):
        return self.request('POST', payload=payload)

    def update(self, record_id, payload):
        if not re.fullmatch(r'[a-f0-9]{16,64}', record_id):
            raise DNSUpdateError('Invalid DNS record ID')
        return self.request('PATCH', '/' + record_id, payload)


def reconcile(api, config, address, initialize=False):
    address = str(ipaddress.IPv6Address(address))
    if ipaddress.ip_address(address) not in ipaddress.ip_network('2000::/3'):
        raise DNSUpdateError('Refusing a non-public IPv6 address')
    specs = config['records']
    names = [spec['name'] for spec in specs]
    if not names or len(names) != len(set(names)):
        raise DNSUpdateError('Empty or duplicate configured DNS names')
    plan = []
    for spec in specs:
        name, owner = spec['name'], spec['comment']
        if not name.endswith('.' + config['zone_name']) or not owner:
            raise DNSUpdateError('DNS name or ownership marker is invalid')
        all_records = api.records(name)
        if any(record.get('name') != name or record.get('type') == 'CNAME' for record in all_records):
            raise DNSUpdateError(f'{name}: conflicting DNS name or CNAME')
        # A is a separately managed, fixed IPv4 fallback. DDNS owns only AAAA.
        records = [record for record in all_records if record.get('type') == 'AAAA']
        if not records:
            if not initialize:
                raise DNSUpdateError(f'{name}: missing record; explicit initialization required')
            record = None
        elif len(records) != 1:
            raise DNSUpdateError(f'{name}: expected exactly one owned AAAA record')
        else:
            record = records[0]
            if record.get('name') != name or record.get('type') != 'AAAA' or record.get('comment') != owner:
                raise DNSUpdateError(f'{name}: DNS ownership or type changed')
        payload = dict(type='AAAA', name=name, content=address, ttl=120, proxied=False, comment=owner)
        plan.append((record, payload))
    # Validate every target before changing any record; never adopt unrelated names.
    outcomes = []
    for record, payload in plan:
        changed = record is None or any(record.get(key) != value for key, value in payload.items())
        if record is None:
            result = api.create(payload)
        elif changed:
            result = api.update(record['id'], payload)
        else:
            result = record
        if any(result.get(key) != value for key, value in payload.items()):
            raise DNSUpdateError(f"{payload['name']}: unexpected DNS API result")
        outcomes.append(dict(name=payload['name'], changed=changed))
    return dict(address=address, ttl=120, proxied=False, records=outcomes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/config/ddns.json')
    parser.add_argument('--initialize', action='store_true', help='Create missing configured records once')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    address = current_address(config.get('interface', 'wlan0'))
    api = Cloudflare(config['zone_id'], config['token_file'])
    print(json.dumps(reconcile(api, config, address, initialize=args.initialize)))


if __name__ == '__main__':
    main()
