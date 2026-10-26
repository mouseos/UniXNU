"""Real DTS-to-ADT checks for opt-in migration overrides and refusal paths."""
from pathlib import Path
import copy
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unixnu import devicetree as dt
from unixnu.util import Error


def read_adt(blob, at=0):
    properties, children = struct.unpack_from('<II', blob, at)
    at += 8
    props, nodes = {}, {}
    for _ in range(properties):
        name, length = struct.unpack_from('<32sI', blob, at)
        at += 36
        props[name.rstrip(b'\0').decode()] = blob[at:at + length]
        at += (length + 3) & ~3
    for _ in range(children):
        child, at = read_adt(blob, at)
        nodes[child['properties']['name'].rstrip(b'\0').decode()] = child
    return {'properties': props, 'children': nodes}, at


class AdtOverridesTest(unittest.TestCase):
    def test_explicit_window_typed_omissions_and_default(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.dts'
            target = Path(directory) / 'test.dtb'
            source.write_text('''/dts-v1/;
/ { #address-cells = <2>; #size-cells = <2>; model = "test"; compatible = "test,board";
 memory@40000000 { device_type = "memory"; reg = <0 0x40000000 0 0x10000000>; };
 cpus { #address-cells = <1>; #size-cells = <0>; timebase-frequency = <13000000>;
 cpu@0 { device_type = "cpu"; compatible = "arm,cortex-a35"; reg = <0>; }; };
 serial@11005000 { reg = <0 0x11005000 0 0x1000>; unixnu,adt-name = "uart0";
 compatible = "ns16550a"; reg-shift = <2>; reg-io-width = <4>; };
};''')
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(target), str(source)], check=True)
            config = {'adt': {'root': {'string': {'compatible': 'OS'}},
                              'product': {'string': {'old': 'inherited'}, 'audio': {'u32': {'value': 1}}}}}
            default = read_adt(dt.generate(target, config))[0]
            self.assertEqual(default['properties']['compatible'], b'OS\0test,board\0')
            self.assertIn('audio', default['children']['product']['children'])
            uart = default['children']['arm-io']['children']['uart0']['properties']
            self.assertEqual(uart['reg-shift'], struct.pack('<I', 2))
            self.assertEqual(uart['reg-io-width'], struct.pack('<I', 4))
            explicit = copy.deepcopy(config)
            explicit['device_tree'] = {'arm_io_base': '0x10000000', 'arm_io_size': '0x10000000'}
            explicit['adt']['root']['omit_properties'] = ['compatible']
            explicit['adt']['product']['omit_properties'] = ['old']
            explicit['adt']['product']['omit_children'] = ['audio']
            result = read_adt(dt.generate(target, explicit))[0]
            self.assertEqual(result['properties']['compatible'], b'test,board\0')
            self.assertEqual(result['children']['arm-io']['properties']['ranges'], struct.pack('<QQQ', 0, 0x10000000, 0x10000000))
            self.assertNotIn('old', result['children']['product']['properties'])
            self.assertFalse(result['children']['product']['children'])
            for window in [{'arm_io_base': '0x10000000'}, {'arm_io_base': '0', 'arm_io_size': '0x10000000'},
                           {'arm_io_base': '0x12000000', 'arm_io_size': '0x1000000'}]:
                with self.subTest(window=window), self.assertRaises(Error):
                    dt.generate(target, {'device_tree': window})
            for key in ['omit_properties', 'omit_children']:
                with self.subTest(key=key), self.assertRaises(Error):
                    dt.generate(target, {'adt': {'product': {key: 'bad type'}}})
            self.assertIn('audio', config['adt']['product'])


if __name__ == '__main__':
    unittest.main()
