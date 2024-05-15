import os
import platform

from avocado.utils import download
from avocado.utils import process

from virttest import data_dir
from virttest import remote
from virttest.libvirt_xml import vm_xml
from virttest.libvirt_xml.devices import disk

from provider.guest_os_booting import guest_os_booting_base


def parse_cdroms_attrs(params):
    """
    Parse cdrom devices' attrs

    :param params: Dictionary with the test parameters
    :return: (boot image path, list of cdrom devices' attrs)
    """

    boot_img_path = os.path.join(data_dir.get_data_dir(), 'images', 'boot.iso')
    cdrom1_attrs = eval(params.get('cdrom1_attrs', '{}'))
    cdrom2_attrs = eval(params.get('cdrom2_attrs', '{}'))
    cdrom_attrs_list = []
    if cdrom1_attrs:
        cdrom_attrs_list.append(cdrom1_attrs)
    if cdrom2_attrs:
        cdrom_attrs_list.append(cdrom2_attrs)

    if cdrom1_attrs.get('source') or cdrom2_attrs.get('source'):
        cmd = "dnf repolist -v enabled |awk '/Repo-baseurl.*composes.*BaseOS.*os/ {print $NF}'"
        repo_url = process.run(cmd, shell=True).stdout_text.strip()
        boot_img_url = os.path.join(repo_url, 'images', 'boot.iso')
        if os.path.exists(boot_img_path):
            os.remove(boot_img_path)
        download.get_file(boot_img_url, boot_img_path)
    return boot_img_path, cdrom_attrs_list


def update_vm_xml(vm, params, cdrom_attrs_list):
    """
    Update VM xml

    :param vm: VM object
    :param params: Dictionary with the test parameters
    :param cdrom_attrs_list: List of cdrom devices' attrs
    """
    os_attrs_boots = eval(params.get('os_attrs_boots', '[]'))
    vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm.name)
    os_attrs = {}
    if os_attrs_boots:
        os_attrs = {'boots': os_attrs_boots}
        vmxml.setup_attrs(os=os_attrs)
    else:
        vm_os = vmxml.os
        vm_os.del_boots()
        vmxml.os = vm_os
    if "yes" == params.get("check_bootable_iso", "no"):
        os_attrs.update({'bootmenu_enable': 'yes',
                         'bootmenu_timeout': '3000'})
        if platform.machine() == "x86_64":
            os_attrs.update({'bios_useserial': 'yes'})
        vmxml.setup_attrs(os=os_attrs)

    index = 0
    for cdrom_attrs in cdrom_attrs_list:
        disk_obj = disk.Disk(cdrom_attrs)
        disk_obj.setup_attrs(**cdrom_attrs)
        vmxml.add_device(disk_obj)
        index += 1
        if 'cdrom_boot_order' in params.get("shortname"):
            vmxml.set_boot_order_by_target_dev(
                cdrom_attrs['target']['dev'], index)
    vmxml.xmltreefile.write()
    vmxml.sync()


def run(test, params, env):
    """
    Boot VM from cdrom devices
    This case covers per-device(cdrom) boot elements and os/boot elements.
    """
    vm_name = guest_os_booting_base.get_vm(params)
    status_error = "yes" == params.get("status_error", "no")
    check_bootable_iso = "yes" == params.get("check_bootable_iso", "no")
    bootable_patterns = eval(params.get('bootable_patterns', '[]'))

    vm = env.get_vm(vm_name)
    vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm.name)
    bkxml = vmxml.copy()
    boot_img_path = None

    try:
        boot_img_path, cdrom_attrs_list = parse_cdroms_attrs(params)
        update_vm_xml(vm, params, cdrom_attrs_list)
        test.log.debug(vm_xml.VMXML.new_from_dumpxml(vm.name))

        vm.start()
        if check_bootable_iso:
            vm.serial_console.read_until_output_matches(
                bootable_patterns, timeout=60, internal_timeout=0.5)
        else:
            try:
                vm.wait_for_serial_login().close()
            except remote.LoginTimeoutError as detail:
                if status_error:
                    test.log.debug("Found the expected error: %s", detail)
                else:
                    test.fail(detail)
    finally:
        bkxml.sync()
        if boot_img_path and os.path.isfile(boot_img_path):
            test.log.debug(f"removing {boot_img_path}")
            os.remove(boot_img_path)
