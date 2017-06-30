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
import numpy as np
import os
import re
import sys
import time

sys.path.append(".")
from oslo_config import cfg

from check_mk_agent.agent.common import config
from check_mk_agent.agent.linux import utils
from check_mk_agent.common import utils as cutils
from check_mk_agent.devices import devices

LOG = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__),
                           '../etc/agent/check_mk_agent_process.conf')
default_argv = ['--config-file', CONFIG_PATH]

def np_process_array(value):
    np_array = np.array(value)
    return {
        'min': round(np.min(np_array), 2),
        'max': round(np.max(np_array), 2),
        'mean': round(np.mean(np_array), 2),
        'std': round(np.std(np_array), 2)
    }

def process_cpu_infos(cpu_infos):
    cpu_fields = cfg.CONF.cpu_fields.split(",")
    LOG.info("cpu_fields: %s", cpu_fields)
    result = {}
    cpu_num = re.compile("^cpu\d")
    for cpu_key, cpu_value in cpu_infos.items():
        if cpu_num.search(cpu_key):
            if cfg.CONF.show_cpu_details:
                mute_idlecpu = float(cfg.CONF.mute_idlecpu)
                if cpu_value.get("idle"):
                    idle_dict = np_process_array(cpu_value['idle'])
                    if idle_dict.get("mean", 0) > mute_idlecpu:
                        continue
            else:
                continue
        result[cpu_key] = {}
        for key, value in cpu_value.items():
            if key in cpu_fields:
                result[cpu_key][key] = np_process_array(value)
    return result

def main():
    # the configuration will be read into the cfg.CONF global data structure
    config.parse(sys.argv[1:])
    if not cfg.CONF.config_file:
        config.parse(sys.argv[1:] + default_argv)
        if not cfg.CONF.config_file:
            sys.exit(_("ERROR: unable to find configuration file!"))
    config.setup_logging(cfg.CONF)

    supported_metrics = config.get_supported_metrics()
    LOG.info(_("Supported metrics: %s"), supported_metrics)

    monitor_qemu = cfg.CONF.monitor_qemu
    monitor_ovs_kernel = cfg.CONF.monitor_ovs_kernel
    dp_pid = cfg.CONF.dp_pid

    result_dict = {}
    if "cpu" in supported_metrics:
        raw_data_file = os.path.join("/tmp", "check_mk_agent.out")
        try:
            out_file = open(raw_data_file, "r")
        except IOError as e:
            LOG.error("Failed to open output file %s for processing data "
                      "with error: %s", out_file, str(e))
            raise e

        (start_time, stop_time) = config.get_monitor_time_range()
        LOG.info(_("Process start time: %f, stop_time: %f"), start_time, stop_time)

        json_block = []
        cpu_infos = {}
        count = 0;
        for line in out_file:
            json_block.append(line)
            if line.startswith('}'):
                json_dict = json.loads(''.join(json_block))
                json_block = []
                time_stamp_key = json_dict.keys()[0]
                time_stamp = float(time_stamp_key)
                if start_time and time_stamp < start_time:
                    continue
                if stop_time and time_stamp > stop_time:
                    continue
                raw_data = json_dict[time_stamp_key]
                LOG.debug("raw_data: %s", raw_data)
                cpu_data = raw_data.get("cpu")
                if cpu_data:
                    count += 1
                    for cpu_key,cpu_value in cpu_data.items():
                        if cpu_key not in cpu_infos:
                            cpu_infos[cpu_key] = {}
                        cpu_info = cpu_infos[cpu_key]
                        for key, value in cpu_value.items():
                            if key not in cpu_info:
                                cpu_info[key] = [value]
                            else:
                                cpu_info[key].append(value)
                if dp_pid:
                    dp_cpu_data = raw_data.get("dp-cpu")
                    LOG.info("dp_cpu info: %s", dp_cpu_data)
                    if dp_cpu_data:
                        for cpu_key,cpu_value in dp_cpu_data.items():
                            if cpu_key not in cpu_infos:
                                cpu_infos[cpu_key] = {}
                            cpu_info = cpu_infos[cpu_key]
                            for key, value in cpu_value.items():
                                if key not in cpu_info:
                                    cpu_info[key] = [value]
                                else:
                                    cpu_info[key].append(value)
                if monitor_qemu:
                    qemu_cpu_data = raw_data.get("qemu-cpu")
                    if qemu_cpu_data:
                        for cpu_key,cpu_value in qemu_cpu_data.items():
                            if cpu_key not in cpu_infos:
                                cpu_infos[cpu_key] = {}
                            cpu_info = cpu_infos[cpu_key]
                            for key, value in cpu_value.items():
                                if key not in cpu_info:
                                    cpu_info[key] = [value]
                                else:
                                    cpu_info[key].append(value)

                if monitor_ovs_kernel:
                    ovs_kernel_cpu_data = raw_data.get("ovs-kernel-cpu")
                    LOG.info("kernel info: %s", ovs_kernel_cpu_data)
                    if ovs_kernel_cpu_data:
                        for cpu_key,cpu_value in ovs_kernel_cpu_data.items():
                            if cpu_key not in cpu_infos:
                                cpu_infos[cpu_key] = {}
                            cpu_info = cpu_infos[cpu_key]
                            for key, value in cpu_value.items():
                                if key not in cpu_info:
                                    cpu_info[key] = [value]
                                else:
                                    cpu_info[key].append(value)
        LOG.info(_("Total valid item number: %d, Raw cpu infos: ..."), count)
        np_cpu_infos = process_cpu_infos(cpu_infos)
        result_dict["CPU_STAT"] = np_cpu_infos
        LOG.info(_("Processed cpu infos: %s"), np_cpu_infos)
        if not cfg.CONF.pprint:
            #print "CPU_STAT:\n %s" % json.dumps(np_cpu_infos)
            print json.dumps({"CPU_STAT": np_cpu_infos})
        else:
            print json.dumps({"CPU_STAT": np_cpu_infos}, indent=4)
            #print "CPU_STAT:\n %s" % json.dumps(np_cpu_infos, indent=4)
    if "perf" in supported_metrics:
        rc, stdout = cutils.run_cmd_with_result("cat /tmp/perf-stat.out")
        result_dict["PERF_STAT"] = stdout
        #print "PERF_STAT:\n %s" % stdout
        print json.dumps({"PERF_STAT": stdout})

if __name__ == "__main__":
    main()
