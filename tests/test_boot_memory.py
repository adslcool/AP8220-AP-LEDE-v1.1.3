"""模拟真实 ARM64 gzip FIT，核验原厂启动时的源、目标与保留内存范围。"""
import gzip
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from images import validate_stock_boot
from layouts import adapt_image_makefile
from test_images import fdt,ap_nodes


def boot_image(load=0x44000000, raw_size=0x1100000, image_size=None, reserved=None):
    nodes=ap_nodes();nodes['/']['ap8220,flash-layout']=b'stock\0'
    base='/soc/nand-controller/nand@0/partitions/'
    del nodes[base+'partition@0']
    for name,start,size in [('rootfs1',0,0x3000000),('rootfs2',0x3000000,0x3000000),('usrdata',0x6000000,0x2000000)]:
        nodes[base+f'partition@{start:x}']={'label':name.encode()+b'\0','reg':struct.pack('>II',start,size)}
    nodes['/reserved-memory']={'#address-cells':struct.pack('>I',2),'#size-cells':struct.pack('>I',2)}
    for start,size in reserved or [(0x40000000,0x1000000),(0x4a400000,0x200000)]:
        nodes[f'/reserved-memory/region@{start:x}']={'reg':struct.pack('>QQ',start,size),'no-map':b''}
    raw=bytearray(raw_size);raw[56:60]=b'ARM\x64'
    struct.pack_into('<Q',raw,16,image_size or raw_size)
    return fdt({
        '/images/kernel-1':{'type':b'kernel\0','arch':b'arm64\0','compression':b'gzip\0','load':struct.pack('>I',load),'entry':struct.pack('>I',load),'data':gzip.compress(bytes(raw),mtime=0)},
        '/images/fdt-1':{'type':b'flat_dt\0','data':fdt(nodes)},
        '/configurations/config@ac02':{'kernel':b'kernel-1\0','fdt':b'fdt-1\0'},
    })


class BootMemoryTests(unittest.TestCase):
    def test_stock_boot_accepts_kernel_larger_than_old_16m_gap(self):
        info=validate_stock_boot(boot_image())
        self.assertEqual(info['内核解压地址'],'0x44000000')
        self.assertGreater(info['内核解压长度'],16*1024*1024)

    def test_old_loading_address_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'重叠'):
            validate_stock_boot(boot_image(load=0x41000000))

    def test_large_fit_input_overlapping_output_is_rejected(self):
        image=boot_image()
        with self.assertRaisesRegex(ValueError,'重叠'):
            validate_stock_boot(image+b'\0'*(33*1024*1024-len(image)))

    def test_declared_runtime_memory_counts_beyond_file_length(self):
        with self.assertRaisesRegex(ValueError,'安全窗口'):
            validate_stock_boot(boot_image(image_size=100*1024*1024))

    def test_actual_reserved_memory_is_checked(self):
        with self.assertRaisesRegex(ValueError,'保留内存'):
            validate_stock_boot(boot_image(reserved=[(0x45000000,0x100000)]))

    def test_only_stock_profile_changes_kernel_loading_address(self):
        source='define Device/aliyun_ap8220\n\tSOC := ipq8071\nendef\n'
        self.assertIn('KERNEL_LOADADDR := 0x44000000',adapt_image_makefile(source,'stock'))
        self.assertNotIn('KERNEL_LOADADDR',adapt_image_makefile(source,'large128'))
