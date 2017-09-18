# python-eduvpn-client - The GNU/Linux eduVPN client and Python API
#
# Copyright: 2017, The Commons Conservancy eduVPN Programme
# SPDX-License-Identifier: GPL-3.0+

import json
import logging
import os

import eduvpn.other_nm as NetworkManager
from eduvpn.config import config_path, stored_metadata
from eduvpn.io import write_cert, store_metadata, mkdir_p
from eduvpn.openvpn import format_like_ovpn, parse_ovpn, ovpn_to_nm
from eduvpn.util import make_unique_id
from eduvpn.exceptions import EduvpnException

logger = logging.getLogger(__name__)


def insert_config(settings):
    """
    Add a configuration to the networkmanager

    args:
        settings (dict): a nm settings dict, typically generated by :meth:`ovpn_to_nm()`
    """
    name = settings['connection']['id']
    logger.info("generating or updating OpenVPN configuration with name {}".format(name))
    connection = NetworkManager.Settings.AddConnection(settings)
    return connection


def list_providers():
    """
    List all OpenVPN connections.
    """
    all_ = NetworkManager.Settings.ListConnections()
    vpn_connections = [c.GetSettings()['connection'] for c in all_ if c.GetSettings()['connection']['type'] == 'vpn']
    logger.info("There are {} VPN connections in networkmanager".format(len(vpn_connections)))
    for conn in vpn_connections:
        try:
            metadata = json.load(open(os.path.join(config_path, conn['uuid'] + '.json'), 'r'))
        except Exception as e:
            logger.error("can't load metadata file: " + str(e))
            yield {'uuid': conn['uuid'], 'display_name': conn['id'], 'icon_data': None, 'connection_type': 'unknown'}
        else:
            yield metadata


def store_provider(api_base_uri, profile_id, display_name, token, connection_type, authorization_type,
                   profile_display_name, two_factor, cert, key, config, icon_data, instance_base_uri):
    """Store the eduVPN configuration"""
    logger.info("storing profile with name {} using NetworkManager".format(display_name))
    uuid = make_unique_id()
    ovpn_text = format_like_ovpn(config, cert, key)
    config_dict = parse_ovpn(ovpn_text)
    cert_path = write_cert(cert, 'cert', uuid)
    key_path = write_cert(key, 'key', uuid)
    ca_path = write_cert(config_dict.pop('ca'), 'ca', uuid)
    ta_path = write_cert(config_dict.pop('tls-auth'), 'ta', uuid)
    nm_config = ovpn_to_nm(config_dict, uuid=uuid, display_name=display_name)
    mkdir_p(config_path)
    l = locals()
    store = {i: l[i] for i in stored_metadata}
    store_metadata(uuid, store)
    nm_config['vpn']['data'].update({'cert': cert_path, 'key': key_path, 'ca': ca_path, 'ta': ta_path})
    insert_config(nm_config)
    return uuid


def delete_provider(uuid):
    """
    Delete the network manager configuration by its UUID

    args:
        uuid (str): the unique ID of the configuration
    """
    logger.info("deleting profile with uuid {} using NetworkManager".format(uuid))
    all_connections = NetworkManager.Settings.ListConnections()
    conns = [c for c in all_connections if c.GetSettings()['connection']['uuid'] == uuid]
    if len(conns) != 1:
        raise EduvpnException("{} connections matching uid {}".format(len(conns), uuid))

    conn = conns[0]
    logger.info("removing certificates for {}".format(uuid))
    for f in ['ca', 'cert', 'key', 'ta']:
        path = conn.GetSettings()['vpn']['data'][f]
        logger.info("removing certificate {}".format(path))
        try:
            os.remove(path)
        except (IOError, OSError) as e:
            logger.error("can't remove certificate {}: {}".format(path, e))

    try:
        conn.Delete()
    except Exception as e:
        logger.error("can't remove networkmanager connection: {}".format(str(e)))
        raise

    metadata = os.path.join(config_path, uuid + '.json')
    logger.info("deleting metadata file {}".format(metadata))
    try:
        os.remove(metadata)
    except Exception as e:
        logger.error("can't remove ovpn file: {}".format(str(e)))


def connect_provider(uuid):
    """
    Enable the network manager configuration by its UUID

    args:
        uuid (str): the unique ID of the configuration
    """
    logger.info("connecting profile with uuid {} using NetworkManager".format(uuid))
    connection = NetworkManager.Settings.GetConnectionByUuid(uuid)
    return NetworkManager.NetworkManager.ActivateConnection(connection, "/", "/")


def list_active():
    """
    List active connections

    returns:
        list: a list of NetworkManager.ActiveConnection objects
    """
    logger.info("getting list of active connections")
    return NetworkManager.NetworkManager.ActiveConnections


def disconnect_provider(uuid):
    """
    Disconnect the network manager configuration by its UUID

    args:
        uuid (str): the unique ID of the configuration
    """
    logger.info("Disconnecting profile with uuid {} using NetworkManager".format(uuid))
    conns = [i for i in NetworkManager.NetworkManager.ActiveConnections if i.Uuid == uuid]
    if len(conns) == 0:
        raise EduvpnException("no active connection found with uuid {}".format(uuid))
    for conn in conns:
        NetworkManager.NetworkManager.DeactivateConnection(conn)


def is_provider_connected(uuid):
    """
    checks if a provider is connected

    returns:
        tuple or None: returns ipv4 and ipv6 address if connected
    """
    for active in list_active():
        if uuid == active.Uuid:
            if active.State == 2:  # connected
                return active.Ip4Config.AddressData[0]['address'], active.Ip6Config.AddressData[0]['address']
            else:
                return "", ""


def update_config_provider(uuid, display_name, config):
    """
    Update an existing network manager configuration

    args:
        uuid (str): the unique ID of the network manager configuration
        display_name (str): The new display name of the configuration
        config (str): The new OpenVPN configuration
    """
    logger.info("updating config for {} ({})".format(display_name, uuid))
    config_dict = parse_ovpn(config)
    ca_path = write_cert(config_dict.pop('ca'), 'ca', uuid)
    ta_path = write_cert(config_dict.pop('tls-auth'), 'ta', uuid)
    nm_config = ovpn_to_nm(config_dict, uuid=uuid, display_name=display_name)
    old_conn = NetworkManager.Settings.GetConnectionByUuid(uuid)
    old_settings = old_conn.GetSettings()
    nm_config['vpn']['data'].update({'cert': old_settings['vpn']['data']['cert'],
                                     'key': old_settings['vpn']['data']['key'],
                                     'ca': ca_path, 'ta': ta_path})
    old_conn.Delete()
    insert_config(nm_config)


def update_keys_provider(uuid, cert, key):
    """
    Update the key pare in the network manager configuration. Typically called when the keypair is expired.

    args:
        uuid (str): unique ID of the network manager connection
        cert (str):
        key (str):
    """
    logger.info("updating key pare for uuid {}".format(uuid))
    write_cert(cert, 'cert', uuid)
    write_cert(key, 'key', uuid)


def update_token(uuid, token):
    """
    Update the oauth token configuration. Typically called when the token is expired.

    args:
        uuid (str): Unique ID of the network manager connection
        token (dict): a oauth configuration dict
    """
    logger.info("writing new token information for {}".format(uuid))
    path = os.path.join(config_path, uuid + '.json')
    with open(path, 'r') as f:
        metadata = json.load(f)
    metadata['token'] = token
    with open(path, 'w') as f:
        json.dump(metadata, f)


def vpn_monitor(callback):
    """
    This installs a dbus callback which will be called every time the state of a VPN connection changes.

    args:
        callback (func): a callback function
    """
    for connection in NetworkManager.Settings.ListConnections():
        if connection.GetSettings()['connection']['type'] == 'vpn':
            connection.connect_to_signal('Updated', callback)
