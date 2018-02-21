# PANW Cisco ACI Device Package Configuration Migrator

**Author:** Brian Torres-Gil <btorres-gil@paloaltonetworks.com>

This script migrates tenant configuration for the Palo Alto
Networks Cisco ACI Device Package from Device Package version 1.2 to 1.3.

Migration is necessary to upgrade from 1.2 to 1.3 because there are
some changes in the configuration parameters between these versions.
 These change is due to enhancements that were made to allow for
deeper configuration of some features such as security zones.

Tested on Python 2.7

The following changes are made to a tenant configuration during migration:

- `InterfaceConfig` folders are changed to `Interface` folders
- `Layer3InterfaceConfig` and `Layer2InterfaceConfig` folders are changed
  to `Layer3Interface` and `Layer2Interface` folders, respectively.
- For each `security_zone` parameters, a `Zone` folder is created to represent that Security Zone. Then the `security_zone` parameter is replaced with a `zone` reference to the new `Zone` folder.
- For each `bridge_domain` parameters, a `Vlan` folder is created to represent that Vlan/BridgeDomain. Then the `bridge_domain` parameter is replaced with a `vlan` reference to the new `Vlan` folder.
- Each `default_gateway` parameter is replaced with a `StaticRoute` folder.
- All L4-L7 Clusters that reference Palo Alto Networks Device Package 1.2 are set to reference Device Package 1.3

**IMPORTANT:** Note that it is often unavoidable to experience
downtime during a major ACI Device Package upgrade, but this script
aims to minimize that downtime as much as possible. In many test
cases, there is no downtime at all, but your experience may vary.

**NOT SUPPORTED** This script was created by one of the Palo Alto Networks Device Package
developers, but is not supported by Palo Alto Networks TAC or Cisco TAC.
Everything this script does can be performed manually on Cisco APIC, and it is
provided as a convenience only. If there is interest in having a TAC-supported
migration script, please reach out to ciscoaci@paloaltonetworks.com.

**This software is provided without warranty or guarantee. Use at your own risk.**

## Install

Step 1: Download or git clone this repository to a new directory:

    wget https://github.com/btorresgil/panw-aci-config-migrator/archive/master.zip
    unzip master.zip
    cd panw-aci-config-migrator-master
    
-- or --

    git clone https://github.com/btorresgil/panw-aci-config-migrator.git
    cd panw-aci-config-migrator
    
Step 2: Install dependencies:

    pip install -r requirements.txt

## Usage

**IMPORTANT** Ensure [Palo Alto Networks Device Package 1.3](https://live.paloaltonetworks.com/cisco)
is installed on APIC before proceeding with migration.

Migration happens in 3 steps:

1. Migrate EPG Service Parameters to 1.3 (`--parameters` argument)
2. Migrate DevMgrs, Chassis, and Clusters to 1.3 (`--clusters` argument)
3. Clean up old 1.2 parameters (`--cleanup` argument)

The `--parameters` and `--clusters` arguments can be
combined with the `--revert` argument to undo the last
action if something unexpected happens. Once the `--cleanup`
argument has been used, no reversion is possible after that.

Set connection information for your APIC using the `-u`, `-l`, and
`-p` arguments to specify the URL, Username, and Password for APIC,
respectively.  If any argument is omitted, you will be prompted
for the value.  Passwords are hidden when prompted on the terminal.

One AppProfile can be migrated at a time. Specify the Tenant and
AppProfile you want to migrate. If the `--tenant` or `--app` argument is
not specified when needed, then a list of available options is presented.

**DRY RUN** You can do a dry run to see what changes would take place
without actually making the changes using the `--dry-run` argument.

Example usage combining the above options to do a full migration of a single AppProfile:

    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp --parameters --clusters
    
    # Check that everything migrated correctly, then...
     
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp --cleanup

A more complex configuration with multiple AppProfiles in a Tenant using a Cluster imported from the _common_ tenant:

    # Migrate parameters in each AppProfile first
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp1 --parameters
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp2 --parameters
    
    # Migrate clusters in common tenant
    ./migrator.py -u https://10.1.2.3 -l admin --tenant common --clusters
    
    # Check that everything migrated correctly, then...
    
    # Cleanup the old parameters
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp1 --cleanup
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp2 --cleanup
 
Example of a reversion:

    # Migrate parameters and clusters in same tenant
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp1 --parameters --clusters
    
    # Say now you found a problem and want to revert the clusters back to 1.2
    
    # Revert the parameters and clusters by adding --revert to the end of the last command
    ./migrator.py -u https://10.1.2.3 -l admin --tenant MyTenant --app MyApp1 --parameters --clusters --revert
    
 
## Full CLI argument reference

```
usage: migrator.py [-h] [-u URL] [-l LOGIN] [-p PASSWORD]
                   [--cert-name CERT_NAME] [--key KEY]
                   [--snapshotfiles SNAPSHOTFILES [SNAPSHOTFILES ...]]
                   [--parameters] [--clusters] [--revert] [--cleanup]
                   [--tenant TENANT] [--app APP] [-n] [-d]

Migrates APIC configuration for PANW Device Package 1.2 to 1.3

optional arguments:
  -h, --help            show this help message and exit
  -u URL, --url URL     APIC URL e.g. http://1.2.3.4
  -l LOGIN, --login LOGIN
                        APIC login ID.
  -p PASSWORD, --password PASSWORD
                        APIC login password.
  --cert-name CERT_NAME
                        X.509 certificate name attached to APIC AAA user
  --key KEY             Private key matching given certificate, used to
                        generate authentication signature
  --snapshotfiles SNAPSHOTFILES [SNAPSHOTFILES ...]
                        APIC configuration files
  --tenant TENANT       Name of tenant to migrate (displays choices if not
                        provided)
  --app APP             Name of application profile to migrate (displays
                        choices if not provided)
  -n, --dry-run         Do not make any changes to APIC, only print what would
                        happen
  -d, --debug           Debug mode

actions:
  Actions to take during migration, at least one of these must be specified

  --parameters          Prepare parameters for migration
  --clusters            Trigger migration of clusters using migrated
                        parameters
  --revert              Switch clusters back to 1.2 device package
  --cleanup             Clean up old 1.2 parameters after a migration.
                        WARNING: cannot revert after a cleanup, use cleanup
                        with caution!
```