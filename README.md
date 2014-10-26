Kubernetes Minion Charm
=======================

Cross cloud deployment of kubernetes.


Usage
-----

To get started :


    juju deploy cs:~hazmat/trusty/etcd
    juju deploy cs:~hazmat/trusty/flannel
    juju deploy local:trusty/kubernetes-master
    juju deploy local:trusty/kubernetes

    juju add-relation etcd flannel
    juju add-relation etcd kubernetes
    juju add-relation etcd kubernetes-master
    juju add-relation kubernetes kubernetes-master


To use, get a kubecfg binary (available in binary tarball download)
and point it to the master with :


    $ juju status kubernetes-master | grep public
    public-address: 104.131.108.99
    $ export KUBERNETES_MASTER="104.131.108.99"


Congratulations you know have deployed kubernetes, you can use the
kubecfg tool to deploy the examples.

