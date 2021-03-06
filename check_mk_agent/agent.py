#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Nicira Neworks, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import eventlet
import json
import logging
import os
import sys

from oslo_config import cfg

from check_mk_agent.agent.common import config
from check_mk_agent.agent.linux import utils
from check_mk_agent.common import utils as cutils
from check_mk_agent.devices import devices

LOG = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__),
                           '../etc/agent/check_mk_agent.conf')
default_argv = ['--config-file', CONFIG_PATH]

def main():
    # the configuration will be read into the cfg.CONF global data structure
    config.parse(sys.argv[1:])
    if not cfg.CONF.config_file:
        config.parse(default_argv)
        if not cfg.CONF.config_file:
            sys.exit(_("ERROR: unable to find configuration file!"))
    config.setup_logging(cfg.CONF)
    memory = devices.Memory()
    #hosts = {'hosts':[]}
    host = {'memory': memory.get_device_dict()}
    #hosts['hosts'].append(host)
    cpu = devices.Cpu()
    host['cpu'] = cpu.get_device_dict()
    system = devices.System()
    host['system'] = system.get_device_dict()
    disks = devices.Disks()
    host['disks'] = disks.get_device_dict()
    nets = devices.Nets()
    host['nets'] = nets.get_device_dict()
    print json.dumps(host, indent=4)
    
    

if __name__ == "__main__":
    main()
