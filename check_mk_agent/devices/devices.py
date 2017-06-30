# vim: tabstop=4 shiftwidth=4 softtabstop=4

import logging
import os
import re
import time

from check_mk_agent.agent.linux import utils
from check_mk_agent.devices import abstract_device

LOG = logging.getLogger(__name__)

CPU_SPEED = "cpu MHz"
CPU_TOP = "Cpu(s)"

STATE_RUNNING = 'running'
STATE_DOWN = 'down'

def get_percent(num, total):
    if total == 0:
        return 0
    rc = float(num) / float(total) * 100;
    return round(rc, 2)

class Memory(abstract_device.AbstractDevice):
    """Memory device data collector.

    All variables are in units of KB.
    """

    name = 'memory'

    def get_plain_info(self):
        cmd = ['cat', '/proc/meminfo']
        plain_info = [line.split()
                      for line in utils.execute(cmd).split('\n')
                      if line]
        LOG.debug(_("plain_info: %s"), plain_info)
        return plain_info

    def parse_plain_info(self, plain_info):
        meminfo = self.parse_proc_meminfo(plain_info)
        self.total = meminfo['MemTotal']
        self.used = meminfo['MemTotal'] - meminfo['MemFree']
        self.swapTotal = meminfo['SwapTotal']
        self.swapFree = meminfo['SwapFree']
        self.caches = meminfo['Cached']
        self.buffers = meminfo['Buffers']
        self.active = meminfo['Active']
        self.usage = (float(self.used - self.caches - self.buffers)
                      / float(self.total) * 100)

    def parse_proc_meminfo(self, plain_info):
        return dict([(i[0][:-1], int(i[1])) for i in plain_info])

    def get_device_dict(self):
        return {'total': self.total,
                'used': self.used,
                'swapTotal': self.swapTotal,
                'swapFree': self.swapFree,
                'caches': self.caches,
                'buffers': self.buffers,
                'active': self.active,
                'usage': self.usage}

    def init_device(self, device_dict):
        self.total = device_dict['total']
        self.used = device_dict['used']
        self.swapTotal = device_dict['swapTotal']
        self.swapFree = device_dict['swapFree']
        self.caches = device_dict['caches']
        self.buffers = device_dict['buffers']
        self.active = device_dict['active']
        self.usage = device_dict['usage']

class Cpu(abstract_device.AbstractDevice):
    """Cpu device data collector.
    speed is in units of MHz and other data is in units
    of USER_HZ (1/100ths of a seconds on most architectures
    """

    name = 'cpu'

    def __init__(self, dp_pid=None, qemu_pids=[], ksoftirqd_pids=[], vhost_pids=[]):
        self.cpuinfos = {}
        self.init_device(None)
        super(Cpu, self).__init__()

        if dp_pid:
            self.dp_pid = dp_pid
            pid_plain_info = self.get_pid_plain_info(self.dp_pid)
            self.parse_pid_plain_info(pid_plain_info, self.dp_pid)

        self.qemu_pids = qemu_pids
        LOG.info("Init monitor qemu pids: %s", qemu_pids)
        for qemu_pid in qemu_pids:
            qemu_pid_plain_info = self.get_pid_plain_info(qemu_pid)
            self.parse_pid_plain_info(qemu_pid_plain_info, qemu_pid)

        self.ksoftirqd_pids = ksoftirqd_pids
        self.vhost_pids = vhost_pids
        LOG.info("Init monitor ksoftirqd_pids: %s, vhost_pids: %s", ksoftirqd_pids, vhost_pids)
        for ksoftirqd_pid in ksoftirqd_pids:
            ksoftirqd_pid_plain_info = self.get_pid_plain_info(ksoftirqd_pid)
            self.parse_pid_plain_info(ksoftirqd_pid_plain_info, ksoftirqd_pid)
        for vhost_pid in vhost_pids:
            vhost_pid_plain_info = self.get_pid_plain_info(vhost_pid)
            self.parse_pid_plain_info(vhost_pid_plain_info, vhost_pid)

    def get_plain_info(self):
        """Get plain info of cpu.
        In order of user, nice, system, idle, iowait,
        irq, softirq and steal
        """
        cmd = ['cat', '/proc/stat']
        plain_info = [line.split(' ', 1) 
                      for line in utils.execute(cmd).split('\n')
                      if line and line.find('cpu') != -1]

        speed_cmd = ['cat', '/proc/cpuinfo']
        speed_info = [line.split(':')
                      for line in utils.execute(speed_cmd).split('\n')
                      if line and line.find(CPU_SPEED) != -1]
        plain_info.extend(speed_info)

        #top_cmd = ['top', '-d', '1', '-n', '1', '-b']
        #top_info = [line.split(':')
        #              for line in utils.execute(top_cmd).split('\n')
        #              if line and line.find(CPU_TOP) != -1]
        #plain_info.extend(top_info) 
        return plain_info

    def get_pid_plain_info(self, pid):
        """Get process plain info of cpu.

        In order of user, nice, system, idle, iowait,
        irq, softirq and steal
        """
        stat_file = "/proc/%s/stat" % pid
        cmd = ['cat', stat_file]
        plain_info = [line.split(' ') 
                      for line in utils.execute(cmd).split('\n')]

        LOG.debug("%s pid plain_info: %s", pid, plain_info)
        return plain_info

    def parse_pid_plain_info(self, plain_info, pid):
        cpu_line = plain_info[0]
        self.pid_us[pid] = float(cpu_line[13])
        self.pid_sys[pid] = float(cpu_line[14])
        self.pid_cus[pid] = float(cpu_line[15])
        self.pid_csys[pid] = float(cpu_line[16])

    def parse_pid_plain_info_now(self, plain_info, pid):
        cpu_line = plain_info[0]
        us_now = float(cpu_line[13])
        sys_now = float(cpu_line[14])
        cus_now = float(cpu_line[15])
        csys_now = float(cpu_line[16])

        us_delta = us_now + cus_now - self.pid_us[pid] - self.pid_cus[pid]
        sys_delta = sys_now + csys_now - self.pid_sys[pid] - self.pid_csys[pid]

        pid_cpu_infos = {
            "user": get_percent(us_delta, self.jiffies_interval),
            "system": get_percent(sys_delta, self.jiffies_interval)
        }

        self.pid_us[pid] = us_now
        self.pid_sys[pid] = sys_now
        self.pid_cus[pid] = cus_now
        self.pid_sys[pid] = sys_now

        return pid_cpu_infos

    def parse_plain_info(self, plain_info):
        cpuinfo = dict([(i[0].strip(), i[1].strip()) for i in plain_info ])
        LOG.debug(_("cpu_info: %s"), cpuinfo)
        self.count = len(cpuinfo) - 1
        for key, value in cpuinfo.items():
            if key == CPU_SPEED:
                self.speed = float(value)
            elif not key.find('cpu'):
                v = [float(x) for x in value.split()]
                if len(v) < 8:
                    v = v + [0, 0, 0, 0]  # needed for Linux 2.4
                self.user[key] = v[0]
                self.nice[key] = v[1]
                self.system[key] = v[2]
                self.idle[key] = v[3]
                self.iowait[key] = v[4]
                self.irq[key] = v[5]
                self.softirq[key] = v[6]
                self.steal[key] = v[7]
                self.total[key] = sum(v[0:7])

    def parse_plain_info_now(self, plain_info):
        cpuinfo = dict([(i[0].strip(), i[1].strip()) for i in plain_info ])
        LOG.debug(_("now cpu_info: %s"), cpuinfo)
        self.count = len(cpuinfo) - 1
        jiff_count = 0;
        jiff_total = 0;
        for key, value in cpuinfo.items():
            if key == CPU_SPEED:
                self.speed = float(value)
            elif not key.find('cpu'):
                v = [float(x) for x in value.split()]
                if len(v) < 8:
                    v = v + [0, 0, 0, 0]  # needed for Linux 2.4
                self.user_now[key] = v[0]
                self.nice_now[key] = v[1]
                self.system_now[key] = v[2]
                self.idle_now[key] = v[3]
                self.iowait_now[key] = v[4]
                self.irq_now[key] = v[5]
                self.softirq_now[key] = v[6]
                self.steal_now[key] = v[7]
                self.total_now[key] = sum(v[0:7])

                user_delta = self.user_now[key] - self.user[key]
                nice_delta = self.nice_now[key] - self.nice[key]
                system_delta = self.system_now[key] - self.system[key]
                idle_delta = self.idle_now[key] - self.idle[key]
                iowait_delta = self.iowait_now[key] - self.iowait[key]
                irq_delta = self.irq_now[key] - self.irq[key]
                softirq_delta = self.softirq_now[key] - self.softirq[key]
                steal_delta = self.steal_now[key] - self.steal[key]
                total_delta = self.total_now[key] - self.total[key]

                self.cpuinfos[key] = {
                    'user':    get_percent(user_delta, total_delta),
                    'system':  get_percent(system_delta, total_delta),
                    'nice':    get_percent(nice_delta, total_delta),
                    'idle':    get_percent(idle_delta, total_delta),
                    'iowait':  get_percent(iowait_delta, total_delta),
                    'hardirq': get_percent(irq_delta, total_delta),
                    'softirq': get_percent(softirq_delta, total_delta),
                    'steal':   get_percent(steal_delta, total_delta),
                }

                if key != "cpu":
                    jiff_count += 1
                    jiff_total += float(total_delta)

                self.user[key] = self.user_now[key]
                self.nice[key] = self.nice_now[key]
                self.system[key] = self.system_now[key]
                self.idle[key] = self.idle_now[key]
                self.iowait[key] = self.iowait_now[key]
                self.irq[key] = self.irq_now[key]
                self.softirq[key] = self.softirq_now[key]
                self.steal[key] = self.steal_now[key]
                self.total[key] = self.total_now[key]
        if jiff_count:
            self.jiffies_interval = jiff_total / jiff_count
        return self.cpuinfos

    def get_cpu_now(self):
        plain_info = self.get_plain_info()
        return self.parse_plain_info_now(plain_info)

    def get_dp_cpu_now(self):
        pid_plain_info = self.get_pid_plain_info(self.dp_pid)
        dp_pid_cpuinfos = {}
        dp_pid_cpuinfos["dp_process_cpu"] = self.parse_pid_plain_info_now(pid_plain_info, self.dp_pid)
        return dp_pid_cpuinfos

    def get_ovs_kernel_cpu_now(self, ksoftirqd_pids, vhost_pids):
        ovs_cpu_infos = {}

        init_ksoftirqd_pids = list(set(ksoftirqd_pids) - set(self.ksoftirqd_pids))
        monitor_ksoftirqd_pids = list(set(ksoftirqd_pids) - set(init_ksoftirqd_pids))
        if init_ksoftirqd_pids:
            LOG.info("Init monitor ksoftirqd pids: %s", init_ksoftirqd_pids)
            for ksoftirqd_pid in init_ksoftirqd_pids:
                ksoftirqd_pid_plain_info = self.get_pid_plain_info(ksoftirqd_pid)
                self.parse_pid_plain_info(ksoftirqd_pid_plain_info, ksoftirqd_pid)
        if monitor_ksoftirqd_pids:
            ksoftirqd_cpu_infos = {}
            ovs_cpu_infos['ksoftirqd'] = {}
            ovs_cpu_infos['ksoftirqd']['user'] = 0.0
            ovs_cpu_infos['ksoftirqd']['system'] = 0.0
            for ksoftirqd_pid in monitor_ksoftirqd_pids:
                ksoftirqd_pid_plain_info = self.get_pid_plain_info(ksoftirqd_pid)
                ksoftirqd_cpu_infos[ksoftirqd_pid] = self.parse_pid_plain_info_now(ksoftirqd_pid_plain_info, ksoftirqd_pid)
            for ksoftirqd_pid in monitor_ksoftirqd_pids:
                ovs_cpu_infos['ksoftirqd']['user'] += ksoftirqd_cpu_infos[ksoftirqd_pid]['user']
                ovs_cpu_infos['ksoftirqd']['system'] += ksoftirqd_cpu_infos[ksoftirqd_pid]['system']

        init_vhost_pids = list(set(vhost_pids) - set(self.vhost_pids))
        monitor_vhost_pids = list(set(vhost_pids) - set(init_vhost_pids))
        if init_vhost_pids:
            LOG.info("Init monitor vhost pids: %s", init_vhost_pids)
            for vhost_pid in init_vhost_pids:
                vhost_pid_plain_info = self.get_pid_plain_info(vhost_pid)
                self.parse_pid_plain_info(vhost_pid_plain_info, vhost_pid)
        if monitor_vhost_pids:
            vhost_cpu_infos = {}
            ovs_cpu_infos['vhost'] = {}
            ovs_cpu_infos['vhost']['user'] = 0.0
            ovs_cpu_infos['vhost']['system'] = 0.0
            for vhost_pid in monitor_vhost_pids:
                vhost_pid_plain_info = self.get_pid_plain_info(vhost_pid)
                vhost_cpu_infos[vhost_pid] = self.parse_pid_plain_info_now(vhost_pid_plain_info, vhost_pid)
            for vhost_pid in monitor_vhost_pids:
                ovs_cpu_infos['vhost']['user'] += vhost_cpu_infos[vhost_pid]['user']
                ovs_cpu_infos['vhost']['system'] += vhost_cpu_infos[vhost_pid]['system']

        user_total = 0.0
        system_total = 0.0
        for process, data_dict in ovs_cpu_infos.items():
            user_total += data_dict['user']
            system_total += data_dict['system']

        ovs_cpu_infos['ovs-kernel'] = {}
        ovs_cpu_infos['ovs-kernel']['user'] = user_total
        ovs_cpu_infos['ovs-kernel']['system'] = system_total

        return ovs_cpu_infos

    def get_qemu_cpu_now(self, qemu_pids):
        init_qemu_pids = list(set(qemu_pids) - set(self.qemu_pids))
        monitor_qemu_pids = list(set(qemu_pids) - set(init_qemu_pids))
        if init_qemu_pids:
            LOG.info("Init monitor qemu pids: %s", qemu_pids)
            for qemu_pid in init_qemu_pids:
                qemu_pid_plain_info = self.get_pid_plain_info(qemu_pid)
                self.parse_pid_plain_info(qemu_pid_plain_info, qemu_pid)
        qemu_cpu_infos = {}
        if monitor_qemu_pids:
            for qemu_pid in monitor_qemu_pids:
                qemu_pid_plain_info = self.get_pid_plain_info(qemu_pid)
                qemu_cpu_key = "qemu_%s" % qemu_pid
                qemu_cpu_infos[qemu_cpu_key] = self.parse_pid_plain_info_now(qemu_pid_plain_info, qemu_pid)
        return qemu_cpu_infos

    def get_jiffies_interval(self):
        return self.jiffies_interval

    def get_device_dict(self):
        return self.cpuinfos

    def init_device(self, device_dict):
        self.jiffies_interval = 100

        self.count = {}
        self.user = {}
        self.nice = {}
        self.system = {}
        self.idle = {}
        self.iowait = {}
        self.irq = {}
        self.softirq = {}
        self.steal = {}
        self.total = {}
        self.userHz = {}
        self.speed = {}

        self.count_now = {}
        self.user_now = {}
        self.nice_now = {}
        self.system_now = {}
        self.idle_now = {}
        self.iowait_now = {}
        self.irq_now = {}
        self.softirq_now = {}
        self.steal_now = {}
        self.total_now = {}
        self.userHz_now = {}
        self.speed_now = {}

        self.pid_us = {}
        self.pid_sys = {}
        self.pid_cus = {}
        self.pid_csys = {}

        self.pid_us_now = {}
        self.pid_sys_now = {}
        self.pid_cus_now = {}
        self.pid_csys_now = {}


class System(abstract_device.AbstractDevice):
    """System device data collector."""

    name = 'system'
    def get_plain_info(self):
        """Get plain info of system."""
        cmd = ['cat', '/proc/uptime']
        plain_info = [line.split(' ', 1) 
                      for line in utils.execute(cmd).split('\n')
                      if line]
        return plain_info

    def parse_plain_info(self, plain_info):
        self.uptime = float(plain_info[0][0])
        self.state = STATE_RUNNING

    def get_device_dict(self):
        return {'uptime': self.uptime,
                'state': self.state}

    def init_device(self, device_dict):
        self.uptime = device_dict['uptime']
        self.state = device_dict['state']

class Disks(abstract_device.AbstractDevice):
    """Disk device data collector.

    readTput, writeTput are in units of bytes/sec,
    latency is in units of milliseconds,
    total is in units of MB"""

    name = 'disks'
    def find_diskstat_value(self, mapping_disk, major, minor):
        for k, v in mapping_disk.items():
            if mapping_disk[k][0] == major and mapping_disk[k][1] == minor:
                return mapping_disk[k]
        return [0] * 14

    def get_plain_info(self):
        """Get plain info of system."""
        # Get df info
        excludefs="-x smbfs -x tmpfs -x devtmpfs -x cifs -x iso9660 -x udf -x nfsv4 -x nfs -x mvfs -x zfs"
        df_cmd = ['df', '-PTlm'] + excludefs.split()
        df_info = [line.split() 
                   for line in utils.execute(df_cmd).split('\n')
                   if line]
        del df_info[0]
        mapping_df = {}
        for line in df_info:
            if os.path.islink(line[0]):
                realpath = os.path.realpath(line[0])
                line[0] = os.path.basename(realpath)
            else:
                line[0] = os.path.basename(line[0])
            mapping_df[line[0]] = line
        LOG.debug(_("mapping_df: %s\n"), mapping_df)

        # Get diskstat info
        disk_cmd = ['cat', '/proc/diskstats']
        p = re.compile('x?[shv]d[a-z]*|cciss/c[0-9]+d[0-9]+|emcpower[a-z]+|dm-[0-9]+|VxVM.*')
        disk_info = [line.split() 
                     for line in utils.execute(disk_cmd).split('\n')
                     if line and p.search(line)]
        mapping_disk = {}
        for line in disk_info:
            mapping_disk[line[2]] = map(lambda x: int(x), line[:2]+line[3:14])
            mapping_disk[line[2]].insert(2, line[2])
        LOG.debug(_("mapping_disk: %s\n"), mapping_disk)

        mapping_info = {}
        for k, v in mapping_disk.items():
            if k in mapping_df.keys():
                if mapping_disk[k][1] != 0:
                # Find the Main dev whose minor number is zero
                    diskstat_value = self.find_diskstat_value(mapping_disk, mapping_disk[k][0], 0)
                else:
                    diskstat_value = mapping_disk[k]
                mapping_info[k] = diskstat_value + mapping_df[k]
        LOG.debug(_("mapping_info: %s\n"), mapping_info)
        return mapping_info

    def parse_plain_info(self, plain_info):
        LOG.debug(_("parse_plain_info() called"))
        self.count = len(plain_info)
        self.disks = []
        for name, v in plain_info.items():
            disk = {'name': name}
            # bytes per sec
            disk['readTput'] = v[5] 
            disk['writeTput'] =  v[9]
            # number per sec
            disk['readIos'] = v[3]
            disk['writeIos'] = v[7]
            disk['iops'] = v[3] + v[7]
            # TODO(belin)right now latency is just like iostat's await
            # IO latency per sec
            disk['readLatency'] = v[6]
            disk['writeLatency'] = v[10]
            disk['ioLatency'] = v[6] + v[10]
            # the total ticks doing IO operations,if 100% of util would lead
            # to device saturation
            #disk['ioTotalTicks'] = v[12]
            disk['capacity'] = int(v[16])
            disk['usage'] = int(v[19][:-1])
            self.disks.append(disk)
        
    def get_device_dict(self):
            return {'count': self.count,
                    'disks': self.disks}

    def init_device(self, device_dict):
        self.count = device_dict['count']
        self.disks = device_dict['disks']

    def write_device_file(self, hostname):
        """Write device data into file."""
        for disk in self.disks:
            device_dir = os.path.join(abstract_device.DATA_BASE_DIR, hostname, self.name, disk['name'])
            if not os.path.isdir(device_dir):
                os.makedirs(device_dir, 0o755)
            timestamp = int(time.time())
            for k, v in disk.items():
                file_name = os.path.join(device_dir, k)
                data = _("%(timestamp)d %(value)s\n" % {'timestamp': timestamp,
                                                  'value': v})
                utils.write_file(file_name, data)  


class Nets(abstract_device.AbstractDevice):
    """net devices data collector.

    inOctets, outOctets, tput are in units of Bytes"""

    name = 'nets'

    def get_plain_info(self):
        cmd = ['cat', '/proc/net/dev']
        plain_info = [line.split(':')
                      for line in utils.execute(cmd).split('\n')
                      if line]
        del plain_info[:2]
        LOG.debug(_("plain_info: %s"), plain_info)
        return plain_info

    def parse_plain_info(self, plain_info):
        netinfo = {}
        for line in plain_info:
            k = line[0].strip()
            v = line[1]
            netinfo[k] = map(lambda x: int(x), v.split())
            netstat = 'cat /sys/class/net/' + k +'/carrier'
            netcmd = netstat.split(' ')
            try:
                output = int(utils.execute(netcmd))
            except Exception:
                output = 0
            if output:
                netinfo[k].append(1)
            else:
                netinfo[k].append(0)
        self.nets = []
        for name, v in netinfo.items():
            net = {}
            net['name'] = name
            net['inOctets'] = v[0]
            net['outOctets'] = v[8]
            net['intfErrs'] = v[2] + v[10]
            net['intfState'] = v[16]
            net['tput'] = v[0] + v[8]
            net['pktInRate'] = v[1]
            net['pktOutRate'] = v[9]
            net['pktRate'] = v[1] + v[7] + v[9]
            #TODO(berlin): It seems that perf can test the bandwidth
            net['bandwidth'] = None
            self.nets.append(net)

    def get_device_dict(self):
        return {'nets': self.nets}

    def init_device(self, device_dict):
        self.nets = device_dict['nets']

    def write_device_file(self, hostname):
        """Write device data into file."""
        timestamp = int(time.time())
        for net in self.nets:
            device_dir = os.path.join(abstract_device.DATA_BASE_DIR, hostname, self.name, net['name'])
            if not os.path.isdir(device_dir):
                os.makedirs(device_dir, 0o755)
            for k, v in net.items():
                file_name = os.path.join(device_dir, k)
                data = _("%(timestamp)d %(value)s\n" % {'timestamp': timestamp,
                                                  'value': v})
                utils.write_file(file_name, data)  
