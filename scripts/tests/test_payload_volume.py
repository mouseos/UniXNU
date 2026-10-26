"""Exercise actual mtools output, timestamps, and file round-trip without mounts."""
from pathlib import Path
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unixnu import payload


class PayloadVolumeTest(unittest.TestCase):
    def test_reproducible_zero_fill_and_preserved_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / 'stage'
            nested = stage / 'EFI/UniXNU'
            nested.mkdir(parents=True)
            content = bytes(range(256)) * 17 + b'\0payload-tail\xff'
            source = nested / 'kernel.bin'
            source.write_bytes(content)
            (nested / 'unixnu.toml').write_text('version = 1\n')
            for entry in [stage, *stage.rglob('*')]:
                os.utime(entry, (payload.EPOCH, payload.EPOCH))
            file_epoch = payload.EPOCH + 86400
            os.utime(source, (file_epoch, file_epoch))
            images = [root / 'a.img', root / 'b.img']
            # Replace an existing image as well as creating a fresh one.
            images[0].write_bytes(b'old output must not survive' * 23)
            for image, epoch, zone in zip(images, ['1700000000', '1900000000'], ['Asia/Tokyo', 'America/Los_Angeles']):
                with patch.dict(os.environ, SOURCE_DATE_EPOCH=epoch, TZ=zone):
                    payload.write_volume(stage, image, 'TEST', 64)
            a, b = [image.read_bytes() for image in images]
            self.assertEqual(len(a), 64 * 1024 * 1024)
            self.assertEqual(a, b)
            self.assertEqual(a[67:71], bytes.fromhex('474e4853'))
            self.assertEqual(a[-512:], bytes(512))
            # The volume label directory entry uses the fixed FAT epoch, not wall time.
            sector = struct.unpack_from('<H', a, 11)[0]
            reserved = struct.unpack_from('<H', a, 14)[0]
            fat_size = struct.unpack_from('<I', a, 36)[0]
            root_cluster = struct.unpack_from('<I', a, 44)[0]
            root_offset = (reserved + a[16] * fat_size + (root_cluster - 2) * a[13]) * sector
            label = a[root_offset:root_offset + 32]
            self.assertEqual(label[:11], b'TEST       ')
            self.assertEqual(label[11], 8)
            self.assertEqual(struct.unpack_from('<HH', label, 22), (0, 33))
            actual = subprocess.check_output(['mtype', '-i', str(images[0]), '::/EFI/UniXNU/kernel.bin'])
            self.assertEqual(actual, content)
            extracted = root / 'kernel.bin'
            subprocess.run(['mcopy', '-m', '-i', str(images[0]), '::/EFI/UniXNU/kernel.bin', str(extracted)], check=True,
                           env={**os.environ, 'TZ': 'UTC'})
            self.assertEqual(int(extracted.stat().st_mtime), file_epoch)
            self.assertEqual(int(source.stat().st_mtime), file_epoch)


if __name__ == '__main__':
    unittest.main()
