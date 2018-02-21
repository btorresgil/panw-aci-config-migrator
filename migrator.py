#!/usr/bin/env python

import sys
import os
import logging
from copy import deepcopy


# Add lib directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'acitoolkit'))
import acitoolkit.acitoolkit as aci


class bcolors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'


def parse_args():
    description = 'Migrates APIC configuration for PANW Device Package 1.2 to 1.3'
    creds = aci.Credentials('apic', description)
    commands = creds.add_argument_group('actions', 'Actions to take during migration, at least one of these must be specified')
    commands.add_argument('--parameters', action='store_true', help='Prepare parameters for migration')
    commands.add_argument('--clusters', action='store_true', help='Trigger migration of clusters using migrated parameters')
    commands.add_argument('--revert', action='store_true', help='Switch clusters back to 1.2 device package')
    commands.add_argument('--cleanup', action='store_true', help='Clean up old 1.2 parameters after a migration. WARNING: cannot revert after a cleanup, use cleanup with caution!')
    creds.add_argument('--tenant', help='Name of tenant to migrate (displays choices if not provided)')
    creds.add_argument('--app', help='Name of application profile to migrate (displays choices if not provided)')
    creds.add_argument('-n', '--dry-run', action='store_true', help='Do not make any changes to APIC, only print what would happen')
    creds.add_argument('-d', '--debug', action='store_true', help='Debug mode')
    args = creds.get()
    if not args.tenant or not args.app:
        # Will fail and exit after printing tenants or apps
        return args
    if not args.parameters and not args.clusters and not args.cleanup and not args.revert:
        print('At least one action must be specified. The actions are typically run in this order to perform a migration:')
        print('  parameters -> clusters -> cleanup')
        sys.exit(1)
    if args.revert and (not args.parameters and not args.clusters):
        print('Revert action must be combined with --parameters or --cluster')
        sys.exit(1)
    if args.revert and args.cleanup:
        print('Revert action must be combined with --parameters and --cluster only. Cleanup cannot be reverted.')
        sys.exit(1)
    if args.cleanup and (args.parameters or args.clusters):
        print('Cleanup cannot be combined with another action.')
        print('It is recommended to ensure everything works before performing a cleanup.')
        print('Cleanup cannot be undone and prevents reversion to device package 1.2 in the future.')
        sys.exit(1)
    return args


def print_object_names(objects, objtype):
    print('\n{0} on APIC:\n'.format(objtype))
    for obj in objects:
        print('  {0}'.format(obj.name))


def print_migration(object, tenant, app, epg, other='', action='Migrating'):
    print('{action} {oc}{object}{endc} with key {kc}{key}{endc} in {lc}{tenant}/{app}/{epg}{other}{endc}'.format(
        action=action,
        object=getattr(object, 'name', object),
        key=getattr(object, 'key', 'n/a'),
        tenant=tenant,
        app=app,
        epg=epg,
        other=other,
        oc=bcolors.RED,
        kc=bcolors.BLUE,
        lc=bcolors.GREEN,
        endc=bcolors.ENDC,
    ))


def get_clusters(session, tenant=None):
    query_target_type = 'subtree'
    #apic_class = 'vnsLDevVip,vnsRsMDevAtt'
    apic_class = 'vnsRsMDevAtt,vnsDevMgr,vnsChassis'
    if query_target_type not in ['self', 'children', 'subtree']:
        raise ValueError
    if isinstance(tenant, str):
        raise TypeError
    if tenant is None:
        tenant_url = ''
    else:
        tenant_url = '/tn-%s' % tenant.name
    query_url = ('/api/mo/uni%s.json?query-target=%s&'
                 'target-subtree-class=%s' % (tenant_url, query_target_type, apic_class))
    ret = session.get(query_url)
    resp = []
    if ret.ok:
        data = ret.json()['imdata']
        logging.debug('response returned %s', data)
    else:
        logging.error('Could not get %s. Received response: %s', query_url, ret.text)
        return resp
    return data


def migrate_interface_folder_keys(tenant, app_name):
    """Migrate interface folder keys

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key == 'InterfaceConfig' and not folder.name.endswith('_premigration'):
                changes_made = True
                print_migration(folder, tenant.name, app.name, epg.name)
                # Copy the folder to make a backup
                backup = deepcopy(folder)
                backup.name = backup.name + '_premigration'
                backup.ctrctNameOrLbl = backup.ctrctNameOrLbl + '_premigration'
                epg.add_child(backup)
                # Modify the folder it is DP 1.3 compatible
                folder.key = 'Interface'
                folder.name = folder.name
                subfolders = folder.get_children(aci.Folder)
                for subfolder in subfolders:
                    if subfolder.key not in ('Layer3InterfaceConfig', 'Layer2InterfaceConfig'):
                        continue
                    print_migration(subfolder, tenant.name, app.name, epg.name, '/'+folder.name)
                    # Strip 'Config' off the end of the key
                    subfolder.key = subfolder.key[:15]
    return changes_made


def migrate_zones_and_vlans(tenant, app_name):
    """Migrate zones and vlans

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key != 'Interface':
                continue
            layerfolders = folder.get_children(aci.Folder)
            for layerfolder in layerfolders:
                if layerfolder.key not in ('Layer3Interface', 'Layer2Interface'):
                    continue
                for param in layerfolder.get_children(aci.Parameter):
                    if param.key not in ('security_zone', 'bridge_domain'):
                        continue
                    print_migration(param, tenant.name, app.name, epg.name, '/'+folder.name+'/'+layerfolder.name)
                    changes_made = True
                    # Delete the current in-memory parameter
                    #layerfolder.remove_child(param)
                    param.mark_as_deleted()
                    # Create a new Vlan or Zone folder
                    new_folder = aci.Folder(param.value, epg)
                    new_folder.ctrctNameOrLbl = folder.ctrctNameOrLbl
                    new_folder.devCtxLbl = folder.devCtxLbl
                    new_folder.graphNameOrLbl = folder.graphNameOrLbl
                    new_folder.nodeNameOrLbl = folder.nodeNameOrLbl
                    new_folder.scopedBy = folder.scopedBy
                    new_ref_key = ''
                    if param.key == 'bridge_domain':
                        new_ref_key = 'vlan'
                        new_folder.key = 'Vlan'
                        # Create a reference to new folder
                    elif param.key == 'security_zone':
                        new_ref_key = 'zone'
                        # For zones, add a mode paramter
                        new_folder.key = 'Zone'
                        layer = aci.Parameter('mode', new_folder)
                        layer.key = 'mode'
                        layer.value = layerfolder.key[:6].lower()  # 'layer3' or 'layer2'
                    # Create relation layer folder to point at new folder
                    relation = aci.Relation(param.key+'_rel', layerfolder)
                    relation.key = new_ref_key
                    relation.targetName = new_folder.name
                    param.mark_as_deleted()
    return changes_made
                    

def migrate_default_gateway(tenant, app_name):
    """Migrate default gateway to static route

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key != 'Interface':
                continue
            layerfolders = folder.get_children(aci.Folder)
            for layerfolder in layerfolders:
                if layerfolder.key not in ('Layer3Interface', 'Layer2Interface'):
                    continue
                for param in layerfolder.get_children(aci.Parameter):
                    if param.key != 'default_gateway':
                        continue
                    changes_made = True
                    print_migration(param, tenant.name, app.name, epg.name, '/'+folder.name+'/'+layerfolder.name)
                    # Delete the current in-memory parameter
                    #layerfolder.remove_child(param)
                    param.mark_as_deleted()
                    # Create a new Static Route
                    new_folder = aci.Folder('default_gateway', epg)
                    new_folder.ctrctNameOrLbl = folder.ctrctNameOrLbl
                    new_folder.devCtxLbl = folder.devCtxLbl
                    new_folder.graphNameOrLbl = folder.graphNameOrLbl
                    new_folder.nodeNameOrLbl = folder.nodeNameOrLbl
                    new_folder.scopedBy = folder.scopedBy
                    new_folder.key = 'StaticRoute'
                    # Add paramters to StaticRoute folder
                    nexthop = aci.Parameter('nexthop', new_folder)
                    nexthop.key = 'nexthop'
                    nexthop.value = param.value
                    destination = aci.Parameter('destination', new_folder)
                    destination.key = 'destination'
                    destination.value = '0.0.0.0/0'
    return changes_made


def migrate_clusters(tenant, session):
    """Migrate clusters to new device package

    Args:
        tenant (aci.Tenant): The tenant to modify

    Returns:
        bool: True if changes made, False if no changes made
    """
    result = []
    cluster_rels = get_clusters(session, tenant)
    for cluster in cluster_rels:
        if 'vnsRsMDevAtt' in cluster and cluster['vnsRsMDevAtt']['attributes']['tDn'] == 'uni/infra/mDev-PaloAltoNetworks-PANOS-1.2':
            cluster_name = cluster['vnsRsMDevAtt']['attributes']['dn'].split('/')[2][8:]
            print_migration(cluster_name, tenant.name, '', '', action='Upgrading cluster to 1.3:')
            rsmdevatt = {'attributes': {'tDn': 'uni/infra/mDev-PaloAltoNetworks-PANOS-1.3'}}
            result.append({'vnsLDevVip': {'attributes': {'name': cluster_name},
                                          'children': [{'vnsRsMDevAtt': rsmdevatt}]}})
        elif 'vnsRsDevMgrToMDevMgr' in cluster and cluster['vnsRsDevMgrToMDevMgr']['attributes']['tDn'] == 'uni/infra/mDevMgr-PaloAltoNetworks-Panorama-1.2':
            cluster_name = cluster.name
            print_migration(cluster_name, tenant.name, '', '', action='Upgrading device manager to 1.3:')
            cluster['vnsRsDevMgrToMDevMgr']['attributes']['tDn'] = 'uni/infra/mDevMgr-PaloAltoNetworks-Panorama-1.3'
            result.append(cluster)
        elif 'vnsRsChassisToMChassis' in cluster and cluster['vnsRsChassisToMChassis']['attributes']['tDn'] == 'uni/infra/mChassis-PaloAltoNetworks-Chassis-1.2':
            cluster_name = cluster.name
            print_migration(cluster_name, tenant.name, '', '', action='Upgrading chassis to 1.3:')
            cluster['vnsRsChassisToMChassis']['attributes']['tDn'] = 'uni/infra/mChassis-PaloAltoNetworks-Chassis-1.3'
            result.append(cluster)
    return result


def cleanup_interface_folders(tenant, app_name):
    """Migrate interface folder keys

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key == 'InterfaceConfig' and folder.name.endswith('_premigration'):
                print_migration(
                    object=folder,
                    tenant=tenant.name,
                    app=app.name,
                    epg=epg.name,
                    action='Deleting',
                )
                changes_made = True
                folder.mark_as_deleted()
    return changes_made


def delete_migrated_folders(tenant, app_name):
    """Delete migrated Paramters

    Warnings:
        Cannot be done after a cleanup action!

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key in ('Interface', 'Zone', 'Vlan', 'StaticRoute'):
                # Delete all 1.3 parameters
                print_migration(object=folder, tenant=tenant.name, app=app.name, epg=epg.name, action='Deleting')
                changes_made = True
                folder.mark_as_deleted()
    return changes_made


def revert_interface_folders(tenant, app_name):
    """Revert Parameters back to the way they were

    Warnings:
        Cannot be done after a cleanup action!

    Args:
        tenant (aci.Tenant): The tenant to modify
        app_name (str): Name of AppProfile

    Returns:
        bool: True if changes made, False if no changes made
    """
    changes_made = False
    app = tenant.get_child(aci.AppProfile, app_name)
    if not app:
        print('Error getting AppProfile: {0}'.format(app_name))
        return False
    epgs = app.get_children(aci.EPG)
    for epg in epgs:
        for folder in epg.get_children(aci.Folder):
            if folder.key in ('Interface', 'Zone', 'Vlan', 'StaticRoute'):
                epg.remove_child(folder)
        for folder in epg.get_children(aci.Folder):
            if folder.name.endswith('_premigration'):
                # Restore backup of 1.2 parameters
                print_migration(object=folder, tenant=tenant.name, app=app.name, epg=epg.name, action='Reverting')
                changes_made = True
                backup = deepcopy(folder)
                epg.add_child(backup)
                backup.mark_as_deleted()
                folder.name = folder.name[:-13]
                folder.ctrctNameOrLbl = folder.ctrctNameOrLbl[:-13]
    return changes_made


def revert_clusters(tenant, session):
    """Migrate clusters to new device package

    Args:
        tenant (aci.Tenant): The tenant to modify

    Returns:
        bool: True if changes made, False if no changes made
    """
    result = []
    cluster_rels = get_clusters(session, tenant)
    for cluster in cluster_rels:
        if cluster['vnsRsMDevAtt']['attributes']['tDn'] == 'uni/infra/mDev-PaloAltoNetworks-PANOS-1.3':
            cluster_name = cluster['vnsRsMDevAtt']['attributes']['dn'].split('/')[2][8:]
            print_migration(cluster_name, tenant.name, '', '', action='Reverting cluster to 1.2:')
            rsmdevatt = {'attributes': {'tDn': 'uni/infra/mDev-PaloAltoNetworks-PANOS-1.2'}}
            result.append({'vnsLDevVip': {'attributes': {'name': cluster_name},
                                          'children': [{'vnsRsMDevAtt': rsmdevatt}]}})
        elif 'vnsRsDevMgrToMDevMgr' in cluster and cluster['vnsRsDevMgrToMDevMgr']['attributes']['tDn'] == 'uni/infra/mDevMgr-PaloAltoNetworks-Panorama-1.3':
            cluster_name = cluster.name
            print_migration(cluster_name, tenant.name, '', '', action='Reverting device manager to 1.2:')
            cluster['vnsRsDevMgrToMDevMgr']['attributes']['tDn'] = 'uni/infra/mDevMgr-PaloAltoNetworks-Panorama-1.2'
            result.append(cluster)
        elif 'vnsRsChassisToMChassis' in cluster and cluster['vnsRsChassisToMChassis']['attributes']['tDn'] == 'uni/infra/mChassis-PaloAltoNetworks-Chassis-1.3':
            cluster_name = cluster.name
            print_migration(cluster_name, tenant.name, '', '', action='Reverting chassis to 1.2:')
            cluster['vnsRsChassisToMChassis']['attributes']['tDn'] = 'uni/infra/mChassis-PaloAltoNetworks-Chassis-1.2'
            result.append(cluster)
    return result


def main():
    args = parse_args()
    session = aci.Session(args.url, args.login, args.password)
    resp = session.login()
    if not resp.ok:
        print('%% Could not login to APIC')
        sys.exit(1)

    # Collect list of tenants from APIC
    tenants = aci.Tenant.get(session)
    if not args.tenant:
        # Print tenants and exit
        print('\nPlease specify a tenant with --tenant TENANT_NAME')
        print_object_names(tenants, 'Tenants')
        sys.exit(0)

    tenant = [t for t in tenants if t.name == args.tenant]
    if not tenant:
        print('Tenant {0} not found on APIC'.format(args.tenant))
        sys.exit(1)
    tenant = tenant[0]

    # Collect list of apps from APIC
    apps = aci.AppProfile.get(session, tenant)
    if (args.parameters or args.cleanup) and not args.app:
        # Print apps and exit
        print('\nPlease specify an AppProfile with --app APP_NAME')
        print_object_names(apps, 'AppProfiles')
        sys.exit(0)

    if args.parameters or args.cleanup:
        app = [a for a in apps if a.name == args.app]
        if not app:
            print('AppProfile {0} not found on APIC'.format(args.app))
            sys.exit(1)
        app = app[0]


    if args.dry_run:
        print('This is a dry-run, so none of the following is actually happening...')

    if args.parameters or args.cleanup or (args.revert and args.parameters):
        # Pull entire tenant config with folders, params, and relations
        tenant = aci.Tenant.get_deep(session, [args.tenant], ['vnsFolderInst'], config_only=True)[0]
    else:
        tenant = aci.Tenant(args.tenant)


    changes_made = False
    # Perform in-memory migration
    if args.parameters and not args.revert:
        changes_made = migrate_interface_folder_keys(tenant, args.app) or changes_made
        changes_made = migrate_zones_and_vlans(tenant, args.app) or changes_made
        changes_made = migrate_default_gateway(tenant, args.app) or changes_made

    clusters = []
    if args.clusters and not args.revert:
        clusters = migrate_clusters(tenant, session)
        if clusters:
            changes_made = True

    # Cleanup old 1.2 parameters (after migration)
    if args.cleanup and not args.revert:
        changes_made = cleanup_interface_folders(tenant, args.app) or changes_made

    # Revert to 1.2 parameters
    if args.revert and args.parameters:
        changes_made = delete_migrated_folders(tenant, args.app) or changes_made
        if not args.dry_run and changes_made:
            resp = session.push_to_apic(tenant.get_url(), tenant.get_json())
            if not resp.ok:
                print('%% Error: Could not push configuration to APIC')
                print(resp.text)
                sys.exit(1)
            else:
                print('Pushed changes to APIC')
        changes_made = revert_interface_folders(tenant, args.app) or changes_made

    if args.revert and args.clusters:
        clusters = revert_clusters(tenant, session)
        if clusters:
            changes_made = True

    # Assemble json
    json = tenant.get_json()
    if args.clusters and clusters:
        json['fvTenant']['children'].extend(clusters)
    if args.debug:
        from pprint import pprint
        pprint(json)
    # Apply changes to APIC
    if not args.dry_run:
        if changes_made:
            resp = session.push_to_apic(tenant.get_url(), json)
            if not resp.ok:
                print('%% Error: Could not push configuration to APIC')
                print(resp.text)
                sys.exit(1)
            else:
                print('Pushed changes to APIC')
        else:
            print('No changes made')
    else:
        print('Skipping push to APIC due to dry-run mode')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
