from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/android'))
from update_dns import DNSUpdateError, candidates, reconcile


OLD = '2001:db8:1::10'
NEW = '2001:db8:1::20'
CONFIG = {'zone_name': 'example.org', 'records': [
    {'name': 'phone.example.org', 'comment': 'phone-owned'},
    {'name': 'store.example.org', 'comment': 'store-owned'},
]}


class DNS:
    def __init__(self):
        self.data = {spec['name']: [dict(spec, id=str(i+1)*32, type='AAAA', content=OLD,
                                       ttl=120, proxied=False)]
                     for i, spec in enumerate(CONFIG['records'])}
        self.writes = []

    def records(self, name):
        return deepcopy(self.data.get(name, []))

    def create(self, payload):
        self.writes.append(('create', deepcopy(payload)))
        result = dict(payload, id='a'*32)
        self.data[payload['name']] = [result]
        return result

    def update(self, record_id, payload):
        self.writes.append(('update', deepcopy(payload)))
        result = dict(payload, id=record_id)
        self.data[payload['name']] = [result if record['id'] == record_id else record
                                      for record in self.data[payload['name']]]
        return result


def test_ipv6_change_updates_both_names_then_becomes_noop():
    api = DNS()
    result = reconcile(api, CONFIG, NEW)
    assert all(record['changed'] for record in result['records'])
    assert len(api.writes) == 2
    assert all(write[1]['content'] == NEW and not write[1]['proxied'] for write in api.writes)
    result = reconcile(api, CONFIG, NEW)
    assert not any(record['changed'] for record in result['records'])
    assert len(api.writes) == 2


@pytest.mark.parametrize('conflict', ['owner', 'type', 'duplicate'])
def test_refuses_foreign_records_before_writing_anything(conflict):
    api = DNS()
    record = api.data['store.example.org'][0]
    if conflict == 'owner':
        record['comment'] = 'another-service'
    elif conflict == 'type':
        record['type'] = 'CNAME'
    else:
        api.data['store.example.org'].append(deepcopy(record))
    with pytest.raises(DNSUpdateError):
        reconcile(api, CONFIG, NEW)
    assert api.writes == []


def test_missing_records_require_explicit_initialization():
    api = DNS()
    del api.data['phone.example.org']
    with pytest.raises(DNSUpdateError, match='explicit initialization'):
        reconcile(api, CONFIG, OLD)
    assert api.writes == []
    reconcile(api, CONFIG, OLD, initialize=True)
    assert len(api.writes) == 1 and api.writes[0][0] == 'create'


def test_selects_only_stable_usable_public_addresses():
    address = dict(local=OLD, prefixlen=64, preferred_life_time=100)
    values = [address, dict(address, local=NEW, preferred_life_time=200),
              dict(address, local='fd00::1'), dict(address, local='192.0.2.1'),
              dict(address, local='2001:db8:2::1', temporary=True),
              dict(address, local='2001:db8:2::2', flags=['deprecated']),
              dict(address, local='2001:db8:2::3', tentative=True),
              dict(address, local='2001:db8:2::4', dadfailed=True),
              dict(address, local='2001:db8:2::5', preferred_life_time=0),
              dict(address, local='2001:db8:2::6', prefixlen=128)]
    assert candidates([{'addr_info': values}]) == [NEW, OLD]


def test_repairs_proxy_and_ttl_without_touching_unrelated_names():
    api = DNS()
    api.data['unrelated.example.org'] = [{'type': 'A', 'content': '192.0.2.1'}]
    api.data['phone.example.org'][0].update(proxied=True, ttl=1)
    reconcile(api, CONFIG, OLD)
    assert len(api.writes) == 1
    assert api.writes[0][1]['ttl'] == 120 and api.writes[0][1]['proxied'] is False
    assert api.data['unrelated.example.org'] == [{'type': 'A', 'content': '192.0.2.1'}]


def test_ipv6_changes_preserve_the_fixed_ipv4_fallback():
    api = DNS()
    fixed = dict(id='f'*32, type='A', name='store.example.org', content='192.0.2.10',
                 ttl=300, proxied=False, comment='separate-ipv4-owner')
    api.data['store.example.org'].append(deepcopy(fixed))
    reconcile(api, CONFIG, NEW)
    records = api.data['store.example.org']
    assert fixed in records
    assert next(record for record in records if record['type'] == 'AAAA')['content'] == NEW
    assert all(payload['type'] == 'AAAA' for _, payload in api.writes)
