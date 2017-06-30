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
import time

sys.path.append(".")
from oslo_config import cfg
from check_mk_agent.agent.common import config
from check_mk_agent.agent.linux import utils
from check_mk_agent.common import utils as cutils
from check_mk_agent.devices import devices

LOG = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__),
                           '../etc/agent/check_mk_agent.conf')
default_argv = ['--config-file', CONFIG_PATH]

worker_pool = eventlet.GreenPool(10)

def start_perf_stat(dp_pid):
    rm_file_cmd = "rm -rf /tmp/perf-stat.out"
    cutils.run_cmd_with_result(rm_file_cmd)

    start_perf_cmd = "sudo perf stat -e cycles,instructions,cache-references,cache-misses,bus-cycles,L1-dcache-loads,L1-dcache-load-misses,L1-dcache-stores,dTLB-loads,dTLB-load-misses,dTLB-stores,dTLB-store-misses,iTLB-loads,iTLB-load-misses,LLC-loads,LLC-load-misses,LLC-stores,LLC-store-misses,LLC-prefetches -p %s -o /tmp/perf-stat.out" % dp_pid
    cutils.run_cmd_with_result(start_perf_cmd)

def start_perf_stat_in_worker(dp_pid):
    worker_pool.spawn_n(start_perf_stat, dp_pid)

def start_perf_record(dp_pid):
    rm_file_cmd = "rm -rf /tmp/perf-record.out"
    cutils.run_cmd_with_result(rm_file_cmd)

    start_perf_cmd = "sudo perf record -e cycles,instructions,cache-references,cache-misses,bus-cycles,L1-dcache-loads,L1-dcache-load-misses,L1-dcache-stores,dTLB-loads,dTLB-load-misses,dTLB-stores,dTLB-store-misses,iTLB-loads,iTLB-load-misses,LLC-loads,LLC-load-misses,LLC-stores,LLC-store-misses -p %s -o /tmp/perf-record.out" % dp_pid
    cutils.run_cmd_with_result(start_perf_cmd)

def start_perf_record_in_worker(dp_pid):
    worker_pool.spawn_n(start_perf_record, dp_pid)
    

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

    raw_data_file = os.path.join("/tmp", "check_mk_agent.out")
    try:
        out_file = open(raw_data_file, "w")
    except IOError as e:
        LOG.error("Failed to open output file %s for writing data "
                  "with error: %s", out_file, str(e))
        raise e

    if "perf" in supported_metrics:
        dp_pid = cfg.CONF.dp_pid
        if not dp_pid:
            LOG.error("ERROR: dp pid is MUST for perf monitor")
            sys.exit(_("ERROR: dp pid is MUST for perf monitor"))
        eventlet.spawn_n(start_perf_stat_in_worker, dp_pid)
        eventlet.spawn_n(start_perf_record_in_worker, dp_pid)

    monitor_qemu = cfg.CONF.monitor_qemu
    monitor_ovs_kernel = cfg.CONF.monitor_ovs_kernel
    dp_pid = cfg.CONF.dp_pid

    ksoftirqd_pids = []
    vhost_pids = []
    if monitor_ovs_kernel:
        ksoftirqd_get_cmds = "pgrep ksoftirqd"
        rc, stdout = cutils.run_cmd_with_result(ksoftirqd_get_cmds, is_quite=True)
        if not rc:
            ksoftirqd_pids = [line.strip() for line in stdout.split("\n")
                              if line.strip()]
            LOG.info("Ksoftirqds process pids: %s", ksoftirqd_pids)

        vhost_get_cmds = "pgrep vhost"
        rc, stdout = cutils.run_cmd_with_result(vhost_get_cmds, is_quite=True)
        if not rc:
            vhost_pids = [line.strip() for line in stdout.split("\n")
                          if line.strip()]
            LOG.info("vhost process pids: %s", vhost_pids)


    qemu_pids = []
    if monitor_qemu:
        qemu_get_cmds = "pgrep qemu-system"
        rc, stdout = cutils.run_cmd_with_result(qemu_get_cmds, is_quite=True)
        if not rc:
            qemu_pids = [line.strip() for line in stdout.split("\n")
                         if line.strip()]
            LOG.info("Qemu process pids: %s", qemu_pids)

    if dp_pid:
        cpu = devices.Cpu(dp_pid, qemu_pids=qemu_pids, ksoftirqd_pids=ksoftirqd_pids, vhost_pids=vhost_pids)
    else:
        cpu = devices.Cpu(qemu_pids=qemu_pids, ksoftirqd_pids=ksoftirqd_pids, vhost_pids=vhost_pids)
    time.sleep(1)
    while True:
        timestamp = time.time()
        host_with_timestamp = {timestamp: {}}
        host = host_with_timestamp[timestamp]
        if "mem" in supported_metrics:
            memory = devices.Memory()
            host['mem'] = memory.get_device_dict()
        if 'cpu' in supported_metrics:
            host['cpu'] = cpu.get_cpu_now()
            if dp_pid:
                # LOG.info("Jiffies interval: %f", cpu.get_jiffies_interval())
                host['dp-cpu'] = cpu.get_dp_cpu_now()
            if cfg.CONF.monitor_qemu:
                qemu_get_cmds = "pgrep qemu-system"
                rc, stdout = cutils.run_cmd_with_result(qemu_get_cmds, is_quite=True)
                if not rc:
                    qemu_pids = [line.strip() for line in stdout.split("\n")
                                 if line.strip()]
                    host['qemu-cpu'] = cpu.get_qemu_cpu_now(qemu_pids)
            if monitor_ovs_kernel:
                ksoftirqd_pids = []
                vhost_pids = []
                ksoftirqd_get_cmds = "pgrep ksoftirqd"
                rc, stdout = cutils.run_cmd_with_result(ksoftirqd_get_cmds, is_quite=True)
                if not rc:
                    ksoftirqd_pids = [line.strip() for line in stdout.split("\n")
                                      if line.strip()]

                vhost_get_cmds = "pgrep vhost"
                rc, stdout = cutils.run_cmd_with_result(vhost_get_cmds, is_quite=True)
                if not rc:
                    vhost_pids = [line.strip() for line in stdout.split("\n")
                                  if line.strip()]
                host['ovs-kernel-cpu'] = cpu.get_ovs_kernel_cpu_now(ksoftirqd_pids, vhost_pids)

        if 'system' in supported_metrics:
            system = devices.System()
            host['system'] = system.get_device_dict()
        if 'disks' in supported_metrics:
            disks = devices.Disks()
            host['disks'] = disks.get_device_dict()
        if 'nets' in supported_metrics:
            nets = devices.Nets()
            host['nets'] = nets.get_device_dict()
        result = json.dumps(host_with_timestamp, indent=4)
        out_file.write("\n" + result)
        out_file.flush()
        time.sleep(1)


if __name__ == "__main__":
    main()
