#!/usr/bin/python

import json
import httplib
import os
import time
import subprocess
import sys
import urlparse

from charmhelpers.core import hookenv, host

hooks = hookenv.Hooks()


@hooks.hook('etcd-relation-changed',
            'api-relation-changed',
            'network-relation-changed')
def relation_changed():
    """Connect the parts and go :-)
    """
    template_data = get_template_data()

    # Check required keys
    for k in ('etcd_servers', 'kubeapi_server', 'overlay_type'):
        if not template_data.get(k):
            print("Missing data for %s %s" % (k, template_data))
            return
    print("Running with\n%s" % template_data)

    # Setup kubernetes supplemental group
    setup_kubernetes_group()

    # Register machine via api
    print("Registering machine")
    register_machine(template_data['kubeapi_server'])

    # Register services
    for n in ("cadvisor", "kubelet", "proxy"):
        if render_upstart(n, template_data) or not host.service_running(n):
            print("Starting %s" % n)
            host.service_restart(n)

    # Save the marker (for restarts to detect prev install)
    template_data.save()


def get_template_data():
    rels = hookenv.relations()
    template_data = hookenv.Config()
    template_data.CONFIG_FILE_NAME = ".unit-state"

    overlay_type = get_scoped_rel_attr('network', rels, 'overlay_type')
    etcd_servers = get_rel_hosts('etcd', rels, ('hostname', 'port'))
    api_servers = get_rel_hosts('api', rels, ('hostname', 'port'))

    # kubernetes master isn't ha yet.
    if api_servers:
        api_info = api_servers.pop()
        api_servers = "http://%s:%s" % (api_info[0], api_info[1])

    template_data['overlay_type'] = overlay_type
    template_data['kubelet_bind_addr'] = hookenv.unit_private_ip()
    template_data['proxy_bind_addr'] = hookenv.unit_get('public-address')
    template_data['kubeapi_server'] = api_servers
    template_data['etcd_servers'] = ",".join([
        'http://%s:%s' % (s[0], s[1]) for s in sorted(etcd_servers)])
    template_data['identifier'] = os.environ['JUJU_UNIT_NAME'].replace(
        '/', '-')
    return _encode(template_data)


def _encode(d):
    for k, v in d.items():
        if isinstance(v, unicode):
            d[k] = v.encode('utf8')
    return d


def get_scoped_rel_attr(rel_name, rels, attr):
    private_ip = hookenv.unit_private_ip()
    for r, data in rels.get(rel_name, {}).items():
        for unit_id, unit_data in data.items():
            if unit_data.get('private-address') != private_ip:
                continue
            if unit_data.get(attr):
                return unit_data.get(attr)


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


def register_machine(apiserver, retry=False):
    parsed = urlparse.urlparse(apiserver)
    headers = {"Content-type": "application/json",
               "Accept": "application/json"}
    #identity = hookenv.local_unit().replace('/', '-')
    private_address = hookenv.unit_private_ip()

    with open('/proc/meminfo') as fh:
        info = fh.readline()
        mem = info.strip().split(":")[1].strip().split()[0]
    cpus = os.sysconf("SC_NPROCESSORS_ONLN")

    request = _encode({
        'kind': 'Minion',
        # These can only differ for cloud provider backed instances?
        'id': private_address,
        'hostIP': private_address,
        'resources': {
            'capacity': {
                'mem': mem + ' K',
                'cpu': cpus}}})

    print("Registration request %s" % request)
    conn = httplib.HTTPConnection(parsed.hostname, parsed.port)
    conn.request(
        "POST", "/api/v1beta1/minions",
        json.dumps(request),
        headers)

    response = conn.getresponse()
    result = json.loads(response.read())
    print("Response status:%s reason:%s body:%s" % (
        response.status, response.reason, result))

    if response.status in (200, 202, 409):
        print("Registered")
    elif not retry and response.status in (500,) and result.get(
            'message', '').startswith('The requested resource does not exist'):
        # There's something fishy in the kube api here (0.4 dev), first time we
        # go to register a new minion, we always seem to get this error.
        # https://github.com/GoogleCloudPlatform/kubernetes/issues/1995
        time.sleep(1)
        print("Retrying registration...")
        return register_machine(apiserver, retry=True)
    else:
        print("Registration error")
        raise RuntimeError("Unable to register machine with %s" % request)


def setup_kubernetes_group():
    output = subprocess.check_output(['groups', 'kubernetes'])

    # TODO: check group exists
    if not 'docker' in output:
        subprocess.check_output(
            ['usermod', '-a', '-G', 'docker', 'kubernetes'])


if __name__ == '__main__':
    hooks.execute(sys.argv)
