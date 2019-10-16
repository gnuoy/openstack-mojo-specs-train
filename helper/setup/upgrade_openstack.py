#!/usr/bin/env python3
import argparse
import sys
import utils.mojo_utils as mojo_utils
import utils.mojo_os_utils as mojo_os_utils
import logging
import subprocess

from zaza import model
from zaza.openstack.utilities import (
    cli as cli_utils,
    openstack as openstack_utils,
)


# TODO move to zaza or some other central location
# {application: {target_release: {'add': [peer_rel1, peer_rel2],
#                                 'remove': [peer_rel1, peer_rel2],}}}
RELATION_CHANGES = {
    'ceilometer':
        {'queens':
            {'add':
                ['keystone:identity-credentials',
                 'ceilometer:identity-credentials'
                 ],
             'remove':
                ['keystone:identity-service',
                 'ceilometer:identity-service'
                 ],

             },
         },
}

NEW_CHARMS = {
    'train': {
        'placement': {
            'lts_premier': 'bionic',
            'charm_source': 'cs:~openstack-charmers-next/placement',
            'num_units': 1,
            'origin_config': 'openstack-origin',
            'config': {},
            'relations': [
                ('placement:shared-db', 'mysql:shared-db'),
                ('placement:identity-service', 'keystone:identity-service'),
                ('placement:placement', 'nova-cloud-controller:placement')]}}}


def update_relations(application, target_release):
    if application not in RELATION_CHANGES.keys():
        logging.debug("No relation changes for {}".format(application))
        return
    if target_release not in RELATION_CHANGES[application].keys():
        logging.debug("No relation changes for {} at {}"
                      .format(application, target_release))
        return

    logging.info("Updating relations for {} at {}"
                 .format(application, target_release))
    if RELATION_CHANGES[application][target_release].get('remove'):
        cmd = ['juju', 'remove-relation']
        for peer_rel in (RELATION_CHANGES[application][target_release]
                         ['remove']):
            cmd.append(peer_rel)
        subprocess.check_call(cmd)

    if RELATION_CHANGES[application][target_release].get('add'):
        cmd = ['juju', 'add-relation']
        for peer_rel in RELATION_CHANGES[application][target_release]['add']:
            cmd.append(peer_rel)
        subprocess.check_call(cmd)


def get_upgrade_targets(target_release, current_versions):
    upgrade_list = []
    for svc in current_versions.keys():
        if current_versions[svc] < target_release:
            upgrade_list.append(svc)
    return upgrade_list


def add_new_charms(target_release):
    for charm, charm_data in NEW_CHARMS.get(target_release, {}).items():
        logging.info("Adding charm {}".format(charm))
        deploy_cmd = ['juju', 'deploy', '-n', str(charm_data['num_units'])]
        if charm_data['origin_config']:
            deploy_cmd = deploy_cmd + [
                '--config',
                '{}={}'.format(
                    charm_data['origin_config'],
                    "cloud:{}-{}/proposed" .format(
                        charm_data['lts_premier'],
                        target_release))]
        deploy_cmd = deploy_cmd + [charm_data['charm_source'], charm]
        subprocess.check_call(deploy_cmd)

        if charm_data['config']:
            model.set_application_config(charm, charm_data['config'])

        rel_cmd = ['juju', 'add-relation']
        for relation in charm_data['relations']:
            logging.info("Adding charm relation {} {}".format(
                relation[0],
                relation[1]))
            subprocess.check_call(rel_cmd + [relation[0], relation[1]])


def main(argv):
    cli_utils.setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target_release",
        default='auto', help="Openstack release name to upgrade to or 'auto' "
                             "to have script upgrade based on the lowest value"
                             "across all services")
    options = parser.parse_args()
    target_release = cli_utils.parse_arg(options, 'target_release')
    principle_services = mojo_utils.get_principle_applications()
    current_versions = openstack_utils.get_current_os_versions(
        principle_services)
    if target_release == 'auto':
        # If in auto mode find the lowest value openstack release across all
        # services and make sure all servcies are upgraded to one release
        # higher than the lowest
        lowest_release = mojo_os_utils.get_lowest_os_version(current_versions)
        target_release = mojo_os_utils.next_release(lowest_release)[1]
    # Get a list of services that need upgrading
    needs_upgrade = get_upgrade_targets(target_release, current_versions)
    add_new_charms(target_release)
    mojo_utils.juju_wait_finished()
    for application in openstack_utils.UPGRADE_SERVICES:
        if application['name'] not in principle_services:
            continue
        if application['name'] not in needs_upgrade:
            logging.info('Not upgrading {} it is at {} or higher'.format(
                application['name'],
                target_release)
            )
            continue
        logging.info('Upgrading {} to {}'.format(application['name'],
                                                 target_release))
        # Update required relations
        update_relations(application['name'], target_release)
        ubuntu_version = mojo_utils.get_ubuntu_version(application['name'])
        config = {application['type']['origin_setting']:
                  "cloud:{}-{}/proposed"
                  .format(ubuntu_version, target_release)}
        model.set_application_config(application['name'], config)
        mojo_utils.juju_wait_finished()

if __name__ == "__main__":
    sys.exit(main(sys.argv))
