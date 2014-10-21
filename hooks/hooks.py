#!/usr/bin/python

import json
import httplib
import os
import sys
import urlparse

from charmhelpers.core import hookenv, host

hooks = hookenv.Hooks()


@hooks.hook('config-changed')
def config_changed():
    """
    Called whenever our service configuration changes.
    """


@hooks.hook('start')
def start():
    """
    Start called once on initial installation to start services,
    and subsequently once per boot.
    """


@hooks.hook('etcd-relation-changed', 'api-relation-changed')
def relation_changed():
    """Connect the parts and go :-)
    """
    template_data = get_template_data()

    # Check required keys
    for k in ('etcd_servers', 'kubeapi_server'):
        if not template_data.get(k):
            print "missing required data", k, template_data
            return

    print "Running with\n", template_data

    # Register machine via api, not properly showing up.. afaics
    #print "Registering machine"
    #register_machine(template_data['kubeapi_server'])

    # Register services
    for n in ("cadvisor", "kubelet", "proxy"):
        if render_upstart(n, template_data) or not host.service_running(n):
            print "Starting", n
            host.service_restart(n)

    # Save the marker
    template_data.save()


def get_template_data():
    rels = hookenv.relations()

    template_data = hookenv.Config()
    template_data.CONFIG_FILE_NAME = ".unit-state"

    etcd_servers = get_rel_hosts('etcd', rels, ('hostname', 'port'))
    api_servers = get_rel_hosts('api', rels)

    # kubernetes master isn't ha yet.
    if api_servers:
        api_servers = "http://%s:8080" % api_servers[0]

    template_data['kubelet_bind_addr'] = hookenv.unit_private_ip()
    template_data['proxy_bind_addr'] = hookenv.unit_get('public-address')
    template_data['kubeapi_server'] = api_servers
    template_data['etcd_servers'] = ",".join([
        'http://%s:%s' % (s[0], s[1]) for s in sorted(etcd_servers)])
    template_data['identifier'] = os.environ['JUJU_UNIT_NAME'].replace(
        '/', '-')
    return template_data


def _encode(d):
    for k, v in d.items():
        if isinstance(v, unicode):
            d[k] = v.encode('utf8')


def get_rel_hosts(rel_name, rels, keys=('private-address',)):
    hosts = []
    for r, data in rels.get(rel_name, {}).items():
        for unit_id, unit_data in data.items():
            if unit_id == hookenv.local_unit():
                continue
            values = [unit_data.get(k) for k in keys]
            if not all(values):
                continue
            hosts.append(len(values) == 1 and values[0] or values)
    return hosts


def render_upstart(name, data):
    tmpl_path = os.path.join(
        os.environ.get('CHARM_DIR'), 'files', '%s.upstart.tmpl' % name)

    with open(tmpl_path) as fh:
        tmpl = fh.read()
    rendered = tmpl % data

    tgt_path = '/etc/init/%s.conf' % name

    if os.path.exists(tgt_path):
        with open(tgt_path) as fh:
            contents = fh.read()
        if contents == rendered:
            return False

    with open(tgt_path, 'w') as fh:
        fh.write(rendered)
    return True


def register_machine(apiserver):
    parsed = urlparse.urlparse(apiserver)
    headers = {"Content-type": "application/json",
               "Accept": "application/json"}
    identity = hookenv.local_unit().replace('/', '-'),

    with open('/proc/meminfo') as fh:
        info = fh.readline()
        mem = info.strip().split(":")[1].strip().split()[0]
    cpus = os.sysconf("SC_NPROCESSORS_ONLN")

    request = {
        'kind': 'Minion',
        'id': identity,
        'hostIP': hookenv.unit_private_ip(),
        'resources': {
            'capacity': {
                'mem': mem + ' K',
                'cpu': cpus}}}

    conn = httplib.HTTPConnection(parsed.hostname, parsed.port)
    conn.request(
        "POST", "/api/v1beta1/minions",
        json.dumps(request),
        headers)

    response = conn.getresponse()
    print "result", response.read()
    if not response.status in (200, 202, 409):
        raise RuntimeError("Unable to register machine with %s" % request)

if __name__ == '__main__':
    hooks.execute(sys.argv)
